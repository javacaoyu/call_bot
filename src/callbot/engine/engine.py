"""会话引擎骨架：输入帧流 →（2.4 ASR）→（2.5/2.6 编排）→（2.7 TTS）→ 输出帧流。"""

from __future__ import annotations

import logging
from collections import deque

from callbot.engine.frames import AudioFrame
from callbot.engine.state import EngineState, StateMachine

logger = logging.getLogger(__name__)


class ConversationEngine:
    """单路会话引擎骨架。

    当前职责：输入帧计数、输出帧 FIFO、状态机驱动；
    ASR / 编排 / TTS 在 2.4~2.7 接入。
    """

    def __init__(self) -> None:
        self._state = StateMachine()
        self._output: deque[AudioFrame] = deque()
        self._input_count = 0
        self._closed = False

    @property
    def state(self) -> EngineState:
        """当前会话状态。"""
        return self._state.current

    @property
    def input_frame_count(self) -> int:
        """已接收输入帧数。"""
        return self._input_count

    def start(self) -> None:
        """开始会话：进入 LISTENING。"""
        self._state.transition(EngineState.LISTENING)

    def feed_audio(self, frame: AudioFrame) -> None:
        """接收输入音频帧（2.4 接入流式 ASR）。"""
        if self._closed:
            logger.warning("会话已关闭，忽略输入帧")
            return
        self._input_count += 1
        if self._input_count % 100 == 0:
            logger.debug("已接收 %d 帧", self._input_count)

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
        """结束会话：清空输出并进入 CLOSED 终态。"""
        self._closed = True
        self._output.clear()
        self._state.transition(EngineState.CLOSED)
