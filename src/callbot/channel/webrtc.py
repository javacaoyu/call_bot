"""WebRTC 信令与音频通道。

流程：浏览器经 WebSocket 发送 offer → 后端创建 RTCPeerConnection 回 answer →
双方交换 ICE 建立媒体连接。**音频不走 opus 轨道**（aiortc 的 opus 解码在本环境
输出 48k 假标签 + 逐样本重复的损坏音频，实测 ASR 无法识别），改为浏览器以
16k PCM16 二进制帧经同一 WebSocket 直传，后端直接送入会话引擎做流式 ASR。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
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

from callbot.engine.engine import ConversationEngine
from callbot.engine.frames import AudioFrame
from callbot.engine.state import EngineState
from callbot.providers.asr import ASRResult, FunASRStreamingASR

logger = logging.getLogger(__name__)

SignalMessage = dict[str, Any]

# FunASR 模型为进程级单例（GPU 常驻，多路会话共享）
_SHARED_ASR: FunASRStreamingASR | None = None


def get_shared_asr() -> FunASRStreamingASR:
    """获取进程级 FunASR 单例（首次调用触发模型加载，约 10~20s）。"""
    global _SHARED_ASR
    if _SHARED_ASR is None:
        _SHARED_ASR = FunASRStreamingASR()
        _SHARED_ASR.load()
    return _SHARED_ASR


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


def _prepare_asr(session: Session, websocket: WebSocket) -> asyncio.Task[None]:
    """异步准备 ASR：加载模型（线程内）并挂到会话引擎。"""

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
    """处理一路浏览器信令连接：offer/answer/ICE + 16k PCM 直传转写推送。

    Args:
        websocket: 已 accept 的信令连接。
        manager: 会话管理器。
    """
    session: Session | None = None
    last_audio_at = time.monotonic()
    last_flush_at = 0.0

    async def silence_flusher() -> None:
        """静音自动收尾：超过 0.8s 无音频则 flush 扣住的句尾（VAD 正式版在 3.1）。"""
        nonlocal last_flush_at
        while True:
            await asyncio.sleep(0.2)
            if (
                session is not None
                and session.engine is not None
                and session.engine.state == EngineState.LISTENING
                and time.monotonic() - last_audio_at > 0.8
                and last_audio_at > last_flush_at
            ):
                last_flush_at = time.monotonic()
                session.engine.flush_asr()

    flusher = asyncio.ensure_future(silence_flusher())
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            # 二进制消息 = 16k PCM16 音频帧（浏览器直传）
            if message.get("bytes") is not None:
                last_audio_at = time.monotonic()
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
                _prepare_asr(session, websocket)
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
