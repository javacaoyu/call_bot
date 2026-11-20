"""会话状态机（媒体无关）。"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto

StateChangeCallback = Callable[["EngineState", "EngineState"], None]


class EngineState(Enum):
    """会话状态。

    主循环：LISTENING → THINKING → SPEAKING → LISTENING；
    SPEAKING → LISTENING 即打断入口（P2 全双工时启用）。
    """

    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    CLOSED = auto()


# 合法状态转移表（CLOSED 为终态）
# IDLE → SPEAKING：机器人主动开场白（外呼场景）；LISTENING → SPEAKING：直接应答
_TRANSITIONS: dict[EngineState, set[EngineState]] = {
    EngineState.IDLE: {EngineState.LISTENING, EngineState.SPEAKING, EngineState.CLOSED},
    EngineState.LISTENING: {
        EngineState.THINKING,
        EngineState.SPEAKING,
        EngineState.IDLE,
        EngineState.CLOSED,
    },
    EngineState.THINKING: {EngineState.SPEAKING, EngineState.LISTENING, EngineState.CLOSED},
    EngineState.SPEAKING: {EngineState.LISTENING, EngineState.IDLE, EngineState.CLOSED},
    EngineState.CLOSED: set(),
}


class StateMachine:
    """带合法转移校验与变化回调的会话状态机。"""

    def __init__(self, initial: EngineState = EngineState.IDLE) -> None:
        self._current = initial
        self._callback: StateChangeCallback | None = None

    @property
    def current(self) -> EngineState:
        """当前状态。"""
        return self._current

    def on_change(self, callback: StateChangeCallback) -> None:
        """注册状态变化回调（参数为 from_state 与 to_state）。"""
        self._callback = callback

    def transition(self, to: EngineState) -> bool:
        """尝试转移状态；非法转移返回 False 且状态不变。"""
        if to not in _TRANSITIONS[self._current]:
            return False
        previous = self._current
        self._current = to
        if self._callback is not None:
            self._callback(previous, to)
        return True
