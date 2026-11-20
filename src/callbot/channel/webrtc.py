"""WebRTC 信令与音频通道（端到端半双工链路）。

流程：浏览器 offer/answer/ICE 建立连接 → 16k PCM 二进制直传（opus 链路不可靠，
见 CLAUDE.md 音频链路约束）→ 引擎流式 ASR → 静音收尾触发完整转写 →
编排层（AgentScope）回复 → SpeechJoiner 首 token 即合成 → TTS 音频帧
（JSON base64）推回浏览器播放。半双工：回复期间新转写丢弃。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import av
import numpy as np
from aiortc import (
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.mediastreams import MediaStreamTrack
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from callbot.config import Settings
from callbot.engine.engine import ConversationEngine
from callbot.engine.frames import AudioFrame
from callbot.engine.joiner import SpeechJoiner
from callbot.engine.state import EngineState
from callbot.orchestration.orchestrator import Orchestrator, create_orchestrator
from callbot.providers.asr import ASRResult, FunASRStreamingASR
from callbot.providers.tts import CosyVoice2StreamingTTS

logger = logging.getLogger(__name__)

SignalMessage = dict[str, Any]

# 静音判定阈值（实测：静音 RMS ~30-80，正常语音 ~1300+）
_SILENCE_RMS = 100

# 进程级模型单例（GPU 常驻，多路会话共享）
_SHARED_ASR: FunASRStreamingASR | None = None
_SHARED_TTS: CosyVoice2StreamingTTS | None = None


def get_shared_asr() -> FunASRStreamingASR:
    """获取进程级 FunASR 单例（首次调用触发模型加载，约 10~20s）。"""
    global _SHARED_ASR
    if _SHARED_ASR is None:
        _SHARED_ASR = FunASRStreamingASR()
        _SHARED_ASR.load()
    return _SHARED_ASR


def get_shared_tts() -> CosyVoice2StreamingTTS:
    """获取进程级 CosyVoice2 单例（首次调用触发模型加载，约 10~30s）。"""
    global _SHARED_TTS
    if _SHARED_TTS is None:
        _SHARED_TTS = CosyVoice2StreamingTTS()
        _SHARED_TTS.load()
    return _SHARED_TTS


def validate_message(raw: str) -> SignalMessage | None:
    """解析并校验信令消息，非法消息返回 None。

    Args:
        raw: 原始 JSON 字符串。

    Returns:
        校验通过的 dict；JSON 非法、缺 type、字段类型不符时返回 None。
    """
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict) or "type" not in msg:
        return None
    mtype = msg["type"]
    if mtype in ("offer", "answer") and not isinstance(msg.get("sdp"), str):
        return None
    if mtype == "ice" and not isinstance(msg.get("candidate"), (dict, type(None))):
        return None
    return msg


@dataclass
class Session:
    """单路 WebRTC 会话。"""

    peer: RTCPeerConnection
    id: str
    engine: ConversationEngine | None = None
    tracks: list[MediaStreamTrack] = field(default_factory=list)


class SessionManager:
    """会话登记、查询与清理。"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        """登记会话。"""
        self._sessions[session.id] = session

    def remove(self, session_id: str) -> None:
        """移除会话（不存在时静默）。"""
        self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> Session | None:
        """按 id 查询会话。"""
        return self._sessions.get(session_id)

    @property
    def count(self) -> int:
        """当前会话数。"""
        return len(self._sessions)


def _parse_ice_candidate(candidate: dict[str, Any]) -> RTCIceCandidate | None:
    """把浏览器 toJSON() 的 candidate 转成 aiortc RTCIceCandidate。

    candidate 里的 `candidate` 字段是 SDP 候选行（如
    ``candidate:foundation 1 udp 2122260223 192.168.1.5 54321 typ host ...``），
    aiortc 1.16 无 from_sdp，需自行解析。解析失败返回 None。

    Args:
        candidate: 浏览器 RTCIceCandidate.toJSON() 的结果。

    Returns:
        解析成功的 RTCIceCandidate；格式不合法时返回 None。
    """
    line = candidate.get("candidate")
    if not isinstance(line, str) or not line.startswith("candidate:"):
        return None
    parts = line[len("candidate:") :].split()
    if len(parts) < 8:
        return None
    foundation, component, protocol, priority, ip, port, _, ctype = parts[:8]
    related_address: str | None = None
    related_port: int | None = None
    tcp_type: str | None = None
    i = 8
    while i < len(parts):
        if parts[i] == "raddr" and i + 1 < len(parts):
            related_address = parts[i + 1]
            i += 2
        elif parts[i] == "rport" and i + 1 < len(parts):
            related_port = int(parts[i + 1])
            i += 2
        elif parts[i] == "tcptype" and i + 1 < len(parts):
            tcp_type = parts[i + 1]
            i += 2
        else:
            # generation / ufrag / network-id 等成对字段跳过
            i += 2
    return RTCIceCandidate(
        component=int(component),
        foundation=foundation,
        ip=ip,
        port=int(port),
        priority=int(priority),
        protocol=protocol,
        type=ctype,
        relatedAddress=related_address,
        relatedPort=related_port,
        sdpMid=candidate.get("sdpMid"),
        sdpMLineIndex=candidate.get("sdpMLineIndex"),
        tcpType=tcp_type,
    )


def resample_pcm_to_16k(pcm: np.ndarray, src_rate: int) -> np.ndarray:
    """把 PCM s16 数组（多声道自动降混）重采样到 16k 单声道。

    供未来电话通道等非 WebRTC 音源使用；当前 Web 链路为 PCM 直传不经此函数。

    Args:
        pcm: (channels, samples) int16 数组。
        src_rate: 源采样率。

    Returns:
        (samples,) int16 数组，采样率 16000。
    """
    if pcm.ndim == 1:
        pcm = pcm[np.newaxis, :]
    if pcm.shape[0] > 1:
        # 语音 ASR 只取左声道：麦克风阵列双声道带相位差，
        # 简单平均会产生梳状滤波使语音失真
        pcm = pcm[:1]
    frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
    frame.sample_rate = src_rate
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    frames = resampler.resample(frame)
    frames += resampler.resample(None)  # flush 内部缓冲，保证一次性转换完整
    return np.concatenate([f.to_ndarray().ravel() for f in frames])


def _prepare_asr(  # noqa: ANN001
    session: Session,
    websocket: WebSocket,
    utterance: list[str],
    reply_active: callable,
) -> asyncio.Task[None]:
    """异步准备 ASR：加载模型（线程内）并挂到会话引擎。

    Args:
        session: 会话。
        websocket: 信令连接（转写推送）。
        utterance: 当前轮转写累积缓冲（完整转写用）。
        reply_active: 返回机器人是否正在回复（半双工门控）。
    """

    def send_transcript(result: ASRResult) -> None:
        logger.info("转写: %s", result.text)

        async def _send() -> None:
            try:
                await websocket.send_text(
                    json.dumps(
                        {"type": "transcript", "text": result.text, "is_final": result.is_final}
                    )
                )
            except Exception:  # noqa: BLE001 - WS 已断开时静默
                pass

        asyncio.ensure_future(_send())
        # 半双工：机器人回复期间的新转写不参与下一轮
        if not reply_active():
            utterance.append(result.text)

    async def run() -> None:
        try:
            await websocket.send_text(
                json.dumps({"type": "status", "detail": "ASR 模型加载中（首次约 10~20 秒）..."})
            )
        except Exception:  # noqa: BLE001
            pass
        asr = await asyncio.to_thread(get_shared_asr)  # 模型加载放线程避免阻塞事件循环
        try:
            await websocket.send_text(
                json.dumps({"type": "status", "detail": "模型就绪，请开始说话"})
            )
        except Exception:  # noqa: BLE001
            pass
        assert session.engine is not None
        session.engine.attach_asr(asr, send_transcript)

    return asyncio.ensure_future(run())


async def handle_signaling(websocket: WebSocket, manager: SessionManager) -> None:
    """处理一路浏览器信令连接：信令 + PCM 直传 ASR + 回复管线（TTS 音频推送）。

    Args:
        websocket: 已 accept 的信令连接。
        manager: 会话管理器。
    """
    settings = Settings()
    session: Session | None = None
    last_speech_at = time.monotonic()
    flushed = False
    utterance: list[str] = []
    reply_in_progress = False
    orch: Orchestrator | None = None

    async def send_json(payload: dict[str, Any]) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:  # noqa: BLE001 - WS 已断开时静默
            pass

    async def send_audio(frame: AudioFrame) -> None:
        await send_json(
            {
                "type": "audio",
                "sample_rate": frame.sample_rate,
                "data": base64.b64encode(frame.data).decode(),
            }
        )

    async def run_reply(text: str) -> None:
        """回复管线：编排层 → joiner → 引擎 FIFO → 并发推送音频帧。"""
        nonlocal reply_in_progress
        nonlocal orch
        reply_in_progress = True
        engine = session.engine
        assert engine is not None
        try:
            # 编排器每会话只建一次：多轮对话历史跨轮保留
            if orch is None:
                orch = create_orchestrator(
                    kind=settings.orchestration_backend,
                    base_url=settings.llm_base_url,
                    api_key=settings.llm_api_key,
                    model=settings.llm_model,
                )
            tts = await asyncio.to_thread(get_shared_tts)
            joiner = SpeechJoiner(tts)
            engine.mark_thinking()

            async def tokens() -> AsyncIterator[str]:  # noqa: ANN202
                async for token in orch.stream_reply(text):
                    await send_json({"type": "reply", "text": token})
                    yield token

            async def drain() -> None:
                """并发排空输出 FIFO：帧到达即推送，低延迟。"""
                while True:
                    frame = engine.get_output_frame()
                    if frame is not None:
                        await send_audio(frame)
                    elif not reply_in_progress:
                        break
                    else:
                        await asyncio.sleep(0.01)

            drain_task = asyncio.ensure_future(drain())
            try:
                async for frame in joiner.run(tokens()):
                    engine.enqueue_output(frame)  # 首帧自动进入 SPEAKING
            finally:
                reply_in_progress = False
                await drain_task  # 排空后 get_output_frame 自动回 LISTENING
        except Exception:  # noqa: BLE001
            logger.exception("回复管线失败")
            await send_json({"type": "status", "detail": "回复失败，请重试"})
            reply_in_progress = False

    async def silence_flusher() -> None:
        """静音自动收尾：0.8s 无音频且转写非空 → flush → 触发回复管线。

        门控语义：flushed 标志在新 PCM 到达时重置；空转写不消耗门控
        （避免说话前静音期空触发导致真正的收尾被跳过）。
        """
        nonlocal flushed
        tick = 0
        while True:
            await asyncio.sleep(0.2)
            tick += 1
            delta = time.monotonic() - last_speech_at
            if tick % 10 == 0:  # 每 2 秒心跳诊断
                logger.info(
                    "flusher 心跳: session=%s state=%s reply=%s delta=%.2f flushed=%s "
                    "utterance_len=%d",
                    session is not None,
                    session.engine.state if session and session.engine else None,
                    reply_in_progress,
                    delta,
                    flushed,
                    len(utterance),
                )
            if (
                session is not None
                and session.engine is not None
                and not reply_in_progress
                and session.engine.state == EngineState.LISTENING
                and delta > 0.8
                and not flushed
                and utterance
            ):
                flushed = True
                session.engine.flush_asr()
                text = "".join(utterance).strip()
                utterance.clear()
                if text:
                    logger.info("完整转写: %s", text)
                    await send_json({"type": "utterance", "text": text})
                    asyncio.ensure_future(run_reply(text))

    flusher = asyncio.ensure_future(silence_flusher())
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            # 二进制消息 = 16k PCM16 音频帧（浏览器直传）
            if message.get("bytes") is not None:
                # 能量检测：PCM 持续到达（含静音），只有 RMS 超过阈值才算「说话」
                arr = np.frombuffer(message["bytes"], dtype=np.int16)
                rms = (
                    float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))
                    if len(arr)
                    else 0.0
                )
                if rms >= _SILENCE_RMS:
                    last_speech_at = time.monotonic()
                    flushed = False  # 新语音到达，重置收尾门控
                if session is not None and session.engine is not None:
                    session.engine.feed_audio(AudioFrame(data=message["bytes"]))
                continue

            raw = message.get("text")
            if raw is None:
                continue
            msg = validate_message(raw)
            if msg is None:
                await websocket.send_text(
                    json.dumps({"type": "error", "detail": "bad message"})
                )
                continue

            mtype = msg["type"]
            if mtype == "offer":
                pc = RTCPeerConnection()
                session = Session(peer=pc, id=str(id(pc)))
                manager.add(session)
                session.engine = ConversationEngine()
                session.engine.start()
                _prepare_asr(session, websocket, utterance, lambda: reply_in_progress)
                await pc.setRemoteDescription(
                    RTCSessionDescription(sdp=msg["sdp"], type="offer")
                )
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                assert pc.localDescription is not None
                await websocket.send_text(
                    json.dumps({"type": "answer", "sdp": pc.localDescription.sdp})
                )
            elif mtype == "ice":
                candidate = msg.get("candidate")
                if session is not None and isinstance(candidate, dict):
                    cand = _parse_ice_candidate(candidate)
                    if cand is not None:
                        await session.peer.addIceCandidate(cand)
    except WebSocketDisconnect:
        pass
    finally:
        flusher.cancel()
        if session is not None:
            if session.engine is not None:
                session.engine.stop()  # flush ASR 并进入 CLOSED
            await session.peer.close()
            manager.remove(session.id)
