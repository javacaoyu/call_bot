"""会话引擎骨架：输入帧流 → 流式 ASR（2.4）→（2.5/2.6 编排）→（2.7 TTS）→ 输出帧流。"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable

from callbot.engine.frames import AudioFrame
from callbot.engine.state import EngineState, StateMachine
from callbot.providers.asr import ASRResult, StreamingASR

logger = logging.getLogger(__name__)

# ASR 流式分块：600ms @16k 单声道 PCM16（与 WBS 1.3 实测一致）
_ASR_CHUNK_MS = 600
_ASR_CHUNK_BYTES = 16000 * 2 * _ASR_CHUNK_MS // 1000

TranscriptCallback = Callable[[ASRResult], None]


class ConversationEngine:
    """单路会话引擎骨架。

    当前职责：输入帧计数、ASR 流式转写（2.4）、输出帧 FIFO、状态机驱动；
    编排 / TTS 在 2.5~2.7 接入。
    """

    def __init__(self) -> None:
        self._state = StateMachine()
        self._output: deque[AudioFrame] = deque()
        self._input_count = 0
        self._closed = False
        self._asr: StreamingASR | None = None
        self._asr_buffer = bytearray()
        self._on_transcript: TranscriptCallback | None = None

    @property
    def state(self) -> EngineState:
        """当前会话状态。"""
        return self._state.current

    @property
    def input_frame_count(self) -> int:
        """已接收输入帧数。"""
        return self._input_count

    def attach_asr(
        self,
        asr: StreamingASR,
        on_transcript: TranscriptCallback | None = None,
    ) -> None:
        """挂载流式 ASR 与转写回调（不挂载时 feed_audio 仅计数）。"""
        self._asr = asr
        self._on_transcript = on_transcript

    def start(self) -> None:
        """开始会话：进入 LISTENING。"""
        self._state.transition(EngineState.LISTENING)

    def feed_audio(self, frame: AudioFrame) -> None:
        """接收输入音频帧；累积满 600ms 后成块送入 ASR。"""
        if self._closed:
            logger.warning("会话已关闭，忽略输入帧")
            return
        self._input_count += 1
        if self._input_count % 100 == 0:
            logger.debug("已接收 %d 帧", self._input_count)
        if self._asr is None:
            return
        self._asr_buffer.extend(frame.data)
        while len(self._asr_buffer) >= _ASR_CHUNK_BYTES:
            chunk = AudioFrame(data=bytes(self._asr_buffer[:_ASR_CHUNK_BYTES]))
            del self._asr_buffer[:_ASR_CHUNK_BYTES]
            result = self._asr.process_chunk(chunk, is_final=False)
            if result is not None and self._on_transcript is not None:
                self._on_transcript(result)

    def _emit(self, result: ASRResult | None) -> None:
        """转写结果非空时触发回调。"""
        if result is not None and self._on_transcript is not None:
            self._on_transcript(result)

    def flush_asr(self) -> None:
        """三段式收尾。

        实测：paraformer 在线模型 is_final=True 不会释放解码器扣住的句尾
        （表现为最后 1 个字/词延迟到下次说话才出现），继续喂入后续块才会释放。
        因此：① 剩余真实音频以非 final 送入；② 追喂 2 块静音触发尾部释放；
        ③ 静音块 is_final=True 收尾；最后重置缓存。
        """
        if self._asr is None:
            return
        silence = AudioFrame(data=b"\x00" * _ASR_CHUNK_BYTES)
        if self._asr_buffer:
            data = bytes(self._asr_buffer).ljust(_ASR_CHUNK_BYTES, b"\x00")
            self._asr_buffer.clear()
            self._emit(self._asr.process_chunk(AudioFrame(data=data), is_final=False))
        for _ in range(2):
            self._emit(self._asr.process_chunk(silence, is_final=False))
        self._emit(self._asr.process_chunk(silence, is_final=True))
        self._asr.reset()

    def enqueue_output(self, frame: AudioFrame) -> None:
        """投递输出音频帧（2.7 接入流式 TTS），并进入 SPEAKING。"""
        if self._closed:
            return
        self._output.append(frame)
        if self._state.current != EngineState.SPEAKING:
            self._state.transition(EngineState.SPEAKING)

    def get_output_frame(self) -> AudioFrame | None:
        """取一帧输出音频（FIFO）；队列取空且处于 SPEAKING 时回到 LISTENING。"""
        if self._output:
            return self._output.popleft()
        if self._state.current == EngineState.SPEAKING:
            self._state.transition(EngineState.LISTENING)
        return None

    def stop(self) -> None:
        """结束会话：flush ASR、清空输出并进入 CLOSED 终态。"""
        self.flush_asr()
        self._closed = True
        self._output.clear()
        self._state.transition(EngineState.CLOSED)
