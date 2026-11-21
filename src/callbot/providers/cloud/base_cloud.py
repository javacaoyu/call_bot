"""云端 ASR 公共基类（WBS 4.2）：后台线程 + 同步 WebSocket 轮询收发。

云端流式 ASR 的服务端结果异步到达，而引擎接口 process_chunk 是同步的——
本基类用「同步投递 + 回调直推」桥接：音频经线程安全队列投递，转写结果
经 set_callback 注册的回调直接推送（不走 process_chunk 返回值）。

线程模型：load() 启动 daemon 线程；等待第一帧 → 建连（websockets 同步
API，recv 短超时轮询实现收发并发）→ 会话结束（is_final 收尾窗口或 reset
哨兵）→ 回等待循环。⚠️ 不用 asyncio.to_thread：其默认 executor 线程非
daemon，loop 永不返回时解释器退出会挂死（实测教训）。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

from callbot.engine.frames import AudioFrame
from callbot.providers.asr import ASRResult

logger = logging.getLogger(__name__)

# 关闭当前会话连接的哨兵（线程永久驻留，等待下一轮重建连接）
_CLOSE = object()
# 接收轮询间隔（秒）：云端 ASR 帧间隔 600ms，轮询开销可忽略
_RECV_POLL_S = 0.05
# is_final 已发后等待服务端推完剩余结果的超时（官方建议收到
# is_last_package 确认后再关连接；无该字段时靠超时兜底）
_DRAIN_TIMEOUT_S = 3.0


class CloudASRBase:
    """云端流式 ASR 公共线程模型。

    子类实现协议钩子：
    - _build_url() -> str：鉴权 URL；
    - _handshake_headers() -> dict[str, str]：鉴权 headers（默认空）；
    - _start_frame() -> bytes | None：建连后的首帧（参数初始化）；
    - _encode_audio(data) -> bytes：音频帧编码；
    - _end_frame() -> bytes | None：结束帧（is_final 时）；
    - _parse_message(raw) -> ASRResult | None：服务端消息 → 转写结果。

    reset() 清队列并投递哨兵关当前连接，下一轮 process_chunk 自动重建。
    """

    # 长连接模式（火山大模型 ASR）：is_final 只触发判停静音、不发末包不关连接，
    # 后续音频帧续传——避免「收尾后用户继续说话」的音频积压与新连接延迟
    _keep_connection = False

    def __init__(self) -> None:
        self._callback: Callable[[ASRResult], None] | None = None
        self._send_q: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None

    # -- 子类协议钩子 --
    def _build_url(self) -> str:
        raise NotImplementedError

    def _handshake_headers(self) -> dict[str, str]:
        return {}

    def _start_frame(self) -> str | bytes | None:
        return None

    def _encode_audio(self, data: bytes) -> bytes:
        return data

    def _end_frame(self) -> bytes | None:
        return None

    def _final_frames(self) -> list[str | bytes]:
        """is_final 时额外发送的帧（默认空）。

        火山：判停静音流（bytes）；千问：finish-task 指令（str，文本帧）。
        """
        return []

    def _resume_frames(self) -> list[str | bytes]:
        """final 后恢复发送音频前额外发送的帧（默认空）。

        千问：新任务 run-task（str，文本帧）。
        """
        return []

    def _parse_message(self, raw: bytes | str) -> ASRResult | None:
        raise NotImplementedError

    # -- StreamingASR 接口实现 --
    def load(self) -> None:
        """启动后台线程（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._thread_main, name="cloud-asr", daemon=True
        )
        self._thread.start()

    def set_callback(self, callback: Callable[[ASRResult], None] | None) -> None:
        """注册增量转写回调（云端结果异步到达时直推）。"""
        self._callback = callback

    def process_chunk(
        self, frame: AudioFrame, is_final: bool = False
    ) -> ASRResult | None:
        """投递音频帧（结果经回调直推，返回 None）。"""
        self.load()
        self._send_q.put((frame.data, is_final))
        return None

    def reset(self) -> None:
        """关当前会话连接（清残留音频 + 哨兵）；线程保持等待下一轮。"""
        try:
            while True:
                self._send_q.get_nowait()
        except queue.Empty:
            pass
        self._send_q.put(_CLOSE)

    def _emit(self, result: ASRResult) -> None:
        if self._callback is not None:
            self._callback(result)

    # -- 后台线程（同步 websockets，无事件循环）--
    def _thread_main(self) -> None:
        from websockets.sync.client import connect

        while True:
            first = self._send_q.get()  # 阻塞等待第一帧
            if first is _CLOSE:
                continue  # 无活动连接可关，继续等待
            try:
                with connect(
                    self._build_url(),
                    additional_headers=self._handshake_headers(),
                ) as ws:
                    self._run_session_sync(ws, first)
            except Exception:  # noqa: BLE001 - 单次会话失败不影响后续轮次
                logger.exception("云端 ASR 会话异常，等待下一轮重建")

    def _run_session_sync(self, ws: object, first: object) -> None:
        data, is_final = first  # type: ignore[misc]

        def send_raw(raw: bytes) -> None:
            ws.send(raw)  # type: ignore[attr-defined]

        start = self._start_frame()
        if start is not None:
            send_raw(start)
        first_encoded = self._encode_audio(data)
        if first_encoded is not None:
            send_raw(first_encoded)
        ended = is_final
        end_sent_at: float | None = None
        need_resume = False
        if ended:
            for extra in self._final_frames():
                send_raw(extra)
            if self._keep_connection:
                ended = False  # 长连接模式：不结束会话，后续音频续传
                need_resume = True
            else:
                end = self._end_frame()
                if end is not None:
                    send_raw(end)
                end_sent_at = time.monotonic()
        while True:
            # 1) 收服务端消息（短超时轮询）
            try:
                raw = ws.recv(timeout=_RECV_POLL_S)  # type: ignore[attr-defined]
                result = self._parse_message(raw)
                if result is not None:
                    self._emit(result)
            except TimeoutError:
                pass
            except Exception as exc:  # noqa: BLE001 - 连接关闭视为会话正常结束
                from websockets.exceptions import ConnectionClosed

                if isinstance(exc, ConnectionClosed):
                    return
                raise
            # 2) 处理发送队列
            if not ended:
                try:
                    item = self._send_q.get_nowait()
                except queue.Empty:
                    item = None
                if item is _CLOSE:
                    return  # 会话关闭：直接断连
                if item is not None:
                    chunk, final = item  # type: ignore[misc]
                    encoded = self._encode_audio(chunk)
                    if encoded is not None:
                        if need_resume:
                            for extra in self._resume_frames():
                                send_raw(extra)
                            need_resume = False
                        send_raw(encoded)
                    if final:
                        for extra in self._final_frames():
                            send_raw(extra)
                        if self._keep_connection:
                            # 长连接模式：不结束会话，后续音频续传
                            need_resume = True
                            continue
                        end = self._end_frame()
                        if end is not None:
                            send_raw(end)
                        ended = True
                        end_sent_at = time.monotonic()
            elif (
                end_sent_at is not None
                and time.monotonic() - end_sent_at > _DRAIN_TIMEOUT_S
            ):
                return  # 收尾窗口结束：服务端剩余结果已收完
