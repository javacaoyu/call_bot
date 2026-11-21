"""WebRTC 信令与音频通道（端到端半双工链路）。

流程：浏览器 offer/answer/ICE 建立连接 → 16k PCM 二进制直传（opus 链路不可靠，
见 CLAUDE.md 音频链路约束）→ 引擎流式 ASR → VAD 端点触发完整转写 →
编排层（AgentScope）回复 → SpeechJoiner 首 token 即合成 → TTS 音频帧
（JSON base64）推回浏览器播放。半双工：回复期间新转写丢弃。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
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
from callbot.engine.vad import SileroVAD, VADEvent
from callbot.orchestration.orchestrator import Orchestrator, create_orchestrator
from callbot.providers.asr import ASRResult, StreamingASR
from callbot.providers.base import (
    asr_config_from_settings,
    create_asr,
    create_tts,
    tts_config_from_settings,
)
from callbot.providers.config_store import apply_provider_overrides
from callbot.providers.tts import StreamingTTS

logger = logging.getLogger(__name__)

SignalMessage = dict[str, Any]

# 进程级模型单例（GPU 常驻，多路会话共享）
_SHARED_ASR: StreamingASR | None = None
_SHARED_TTS: StreamingTTS | None = None


def invalidate_shared_providers() -> None:
    """失效模型单例（4.4 Web 面板保存配置后调用）。

    旧实例引用计数归零后由 GC 释放（本地模型显存随之释放）；
    下一路会话 get_shared_* 按新配置重建——热切换。
    """
    global _SHARED_ASR, _SHARED_TTS
    _SHARED_ASR = None
    _SHARED_TTS = None


def get_shared_asr(settings: Settings) -> StreamingASR:
    """获取进程级 ASR 单例（kind 配置驱动切换；首次调用触发模型加载）。"""
    global _SHARED_ASR
    if _SHARED_ASR is None:
        _SHARED_ASR = create_asr(asr_config_from_settings(settings))
        _SHARED_ASR.load()
    return _SHARED_ASR


def get_shared_tts(settings: Settings) -> StreamingTTS:
    """获取进程级 TTS 单例（kind 配置驱动切换；首次调用触发模型加载）。"""
    global _SHARED_TTS
    if _SHARED_TTS is None:
        _SHARED_TTS = create_tts(tts_config_from_settings(settings))
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


def _prepare_models(  # noqa: ANN001
    session: Session,
    websocket: WebSocket,
    utterance: list[str],
    reply_active: callable,
    vad: SileroVAD,
    settings: Settings,
    interrupt_cb: Callable[[], Awaitable[None]],
) -> asyncio.Task[None]:
    """异步准备模型：加载 ASR + VAD（线程内）并挂到会话引擎。

    Args:
        session: 会话。
        websocket: 信令连接（转写推送）。
        utterance: 当前轮转写累积缓冲（完整转写用）。
        reply_active: 返回机器人是否正在回复（半双工门控）。
        vad: 本会话 VAD 实例（状态机在 handle_signaling 中消费）。
        settings: 全局配置（ASR 工厂 kind 分发）。
        interrupt_cb: 打断触发（async）；回复期间转写出字即调用——ASR 驱动
            打断比 VAD 起音（250ms 观察窗）更快。
    """

    async def run() -> None:
        loop = asyncio.get_running_loop()  # 主事件循环（云端 ASR 回调线程用）
        interrupt_fired = False  # 去重：每轮回复只打断一次
        prev_reply_active = False

        def send_transcript(result: ASRResult) -> None:
            nonlocal interrupt_fired, prev_reply_active
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

            # 云端 ASR 结果在后台线程到达：threadsafe 投递到主事件循环
            asyncio.run_coroutine_threadsafe(_send(), loop)
            active = reply_active()
            if active and not prev_reply_active:
                interrupt_fired = False  # 新一轮回复开始，重置打断去重
            prev_reply_active = active
            # ASR 驱动打断：机器人回复期间出字 = 用户抢话（比 VAD 起音快）
            if active and result.text.strip() and not interrupt_fired:
                interrupt_fired = True
                logger.info("ASR 打断触发: %s", result.text)
                asyncio.run_coroutine_threadsafe(interrupt_cb(), loop)
            elif active and result.text.strip():
                logger.info("打断被去重/未触发: text=%s fired=%s", result.text, interrupt_fired)
            # 半双工：机器人回复期间的新转写不参与下一轮
            if not active:
                utterance.append(result.text)

        try:
            await websocket.send_text(
                json.dumps({"type": "status", "detail": "ASR 模型加载中（首次约 10~20 秒）..."})
            )
        except Exception:  # noqa: BLE001
            pass
        asr = await asyncio.to_thread(get_shared_asr, settings)  # 加载放线程避免阻塞事件循环
        await asyncio.to_thread(vad.load)  # VAD 模型 2MB，秒级加载
        try:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "status",
                        "detail": (
                            "模型就绪，请开始说话"
                            f"（ASR={settings.asr_kind} / TTS={settings.tts_kind}）"
                        ),
                    }
                )
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
    apply_provider_overrides(settings)  # Web 面板覆盖层 > env > 默认
    session: Session | None = None
    vad = SileroVAD(
        model_path=settings.vad_model_path,
        threshold=settings.vad_threshold,
        min_speech_ms=settings.vad_min_speech_ms,
        min_silence_ms=settings.vad_min_silence_ms,
    )
    flushed = False
    utterance: list[str] = []
    reply_in_progress = False
    reply_task: asyncio.Task[None] | None = None
    pending_spoken: list[str] = []  # 打断上下文：本轮已完整说出的句子
    interrupted_this_turn = False  # 本轮回复是否被打断过（决定 spoken_prefix 注入）
    audio_seq = 0  # 已发送音频帧序号（每帧递增）
    confirmed_audio_seq = 0  # 前端已确认播放到的帧序号（playback_done 回传）

    def playback_active() -> bool:
        """前端是否仍在播报（已发送帧多于已确认帧）。

        打断窗口 = 后端生成中 或 前端播报中——否则「AI 播报尾声」用户抢话
        会被误判为正常轮次（后端已发完但前端还在播）。
        """
        return audio_seq > confirmed_audio_seq
    orch: Orchestrator | None = None

    async def send_json(payload: dict[str, Any]) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:  # noqa: BLE001 - WS 已断开时静默
            pass

    async def send_audio(frame: AudioFrame) -> None:
        nonlocal audio_seq
        audio_seq += 1
        await send_json(
            {
                "type": "audio",
                "seq": audio_seq,
                "sample_rate": frame.sample_rate,
                "data": base64.b64encode(frame.data).decode(),
            }
        )

    async def run_reply(text: str, spoken_prefix: str | None = None) -> None:
        """回复管线：编排层 → joiner → 引擎 FIFO → 并发推送音频帧。

        spoken_prefix：打断上下文重建素材——打断轮为已说句子（可空串，
        编排层注入占位）；正常轮为 None。
        打断时本 task 被 cancel → token 流 aclose → LLM 关流。
        """
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
            tts = await asyncio.to_thread(get_shared_tts, settings)
            joiner = SpeechJoiner(tts)
            engine.mark_thinking()

            async def tokens() -> AsyncIterator[str]:  # noqa: ANN202
                async for token in orch.stream_reply(text, spoken_prefix):
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

    async def handle_interrupt(started_at: float) -> None:
        """打断动作链（3.3）：停音频 + 关 LLM 流 + 暂存已说句子。

        顺序：引擎清未播队列（拿「已完整说出的句子」快照）→ drain 退出 →
        cancel 回复 task（token 流 aclose → LLM 关流）→ 前端 stop_audio
        立即停播已调度的帧。started_at 为 VAD 起音判定的时刻（埋点计时）。
        """
        nonlocal reply_in_progress, pending_spoken, interrupted_this_turn
        engine = session.engine
        if engine is None:
            return
        logger.info("打断执行: 打断前状态=%s", session.engine.state)
        spoken = engine.interrupt()  # 清队列 + SPEAKING/THINKING → LISTENING
        pending_spoken.extend(spoken)
        interrupted_this_turn = True  # 下一轮回复注入打断占位（保持历史形态）
        reply_in_progress = False
        if reply_task is not None:
            reply_task.cancel()  # 先停音频帧流（drain 随队列清空退出）
        await asyncio.sleep(0)  # 让 cancel 的 task 先退出，stop 消息少排队
        await send_json({"type": "stop_audio"})
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "打断链路完成: %.1fms（起音判定后→stop_audio 发出），已说 %d 句",
            elapsed_ms,
            len(spoken),
        )

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            # 二进制消息 = 16k PCM16 音频帧（浏览器直传）
            if message.get("bytes") is not None:
                frame = AudioFrame(data=message["bytes"])
                event = vad.process_frame(frame)
                if event is VADEvent.SPEECH_START:
                    flushed = False  # 新语音段到达，重置收尾门控
                    if reply_in_progress or playback_active():
                        asyncio.ensure_future(handle_interrupt(time.perf_counter()))
                elif event is VADEvent.SPEECH_END:
                    engine = session.engine if session else None
                    if (
                        engine is not None
                        and not reply_in_progress
                        and not playback_active()
                        and engine.state == EngineState.LISTENING
                        and not flushed
                        and utterance
                    ):
                        flushed = True
                        engine.flush_asr()

                        async def finish_utterance() -> None:
                            """收尾宽限：等云端 ASR 判停增量并入后再送回复。

                            云端实时识别的尾字在判停（~800ms 静音）后才返回；
                            宽限期内的增量继续 append 到 utterance，避免吞尾字。
                            """
                            nonlocal reply_task, interrupted_this_turn
                            await asyncio.sleep(settings.utterance_settle_ms / 1000)
                            text = "".join(utterance).strip()
                            utterance.clear()
                            if text:
                                logger.info("完整转写: %s", text)
                                await send_json({"type": "utterance", "text": text})
                                if interrupted_this_turn:
                                    # 打断轮：注入已说句子（可空，编排层补占位）
                                    prefix: str | None = "".join(pending_spoken)
                                else:
                                    prefix = None
                                pending_spoken.clear()
                                interrupted_this_turn = False
                                reply_task = asyncio.ensure_future(
                                    run_reply(text, prefix)
                                )

                        asyncio.ensure_future(finish_utterance())
                if session is not None and session.engine is not None:
                    session.engine.feed_audio(frame)
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
                _prepare_models(
                    session,
                    websocket,
                    utterance,
                    lambda: reply_in_progress or playback_active(),
                    vad,
                    settings,
                    lambda: handle_interrupt(time.perf_counter()),
                )
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
            elif mtype == "playback_done":
                # 前端确认播放到某帧：打断窗口据此收敛（后端发完 ≠ 前端播完）
                seq = msg.get("seq", 0)
                if isinstance(seq, int):
                    confirmed_audio_seq = max(confirmed_audio_seq, seq)
                    logger.debug("前端确认播放到帧 %d", confirmed_audio_seq)
    except WebSocketDisconnect:
        pass
    finally:
        if session is not None:
            if session.engine is not None:
                session.engine.stop()  # flush ASR 并进入 CLOSED
            await session.peer.close()
            manager.remove(session.id)
