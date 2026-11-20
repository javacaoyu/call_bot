"""会话状态机（媒体无关）。"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto

StateChangeCallback = Callable[["EngineState", "EngineState"], None]
EnterExitCallback = Callable[[], None]


class EngineState(Enum):
    """会话状态。

    主循环：LISTENING → THINKING → SPEAKING → LISTENING；
    SPEAKING/THINKING → LISTENING 即打断入口（3.2 提供 interrupt 语义化转移）。
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
    """带合法转移校验与回调的会话状态机。"""

    def __init__(self, initial: EngineState = EngineState.IDLE) -> None:
        self._current = initial
        self._callback: StateChangeCallback | None = None
        self._enter_callback: EnterExitCallback | None = None
        self._exit_callback: EnterExitCallback | None = None

    @property
    def current(self) -> EngineState:
        """当前状态。"""
        return self._current

    def on_change(self, callback: StateChangeCallback) -> None:
        """注册状态变化回调（参数为 from_state 与 to_state）。"""
        self._callback = callback

    def on_enter(self, callback: EnterExitCallback) -> None:
        """注册进入新状态回调（任何转移成功后触发一次）。"""
        self._enter_callback = callback

    def on_exit(self, callback: EnterExitCallback) -> None:
        """注册离开当前状态回调（任何转移成功前触发一次）。"""
        self._exit_callback = callback

    def transition(self, to: EngineState) -> bool:
        """尝试转移状态；非法转移返回 False 且状态不变。"""
        if to not in _TRANSITIONS[self._current]:
            return False
        previous = self._current
        self._current = to
        if self._exit_callback is not None:
            self._exit_callback()
        if self._callback is not None:
            self._callback(previous, to)
        if self._enter_callback is not None:
            self._enter_callback()
        return True

    def interrupt(self) -> bool:
        """语义化打断转移：SPEAKING/THINKING → LISTENING。

        作为 3.3 打断链路的显式入口（接入层可在此挂停止动作）；
        非 SPEAKING/THINKING 状态（IDLE/LISTENING/CLOSED）返回 False 且状态不变
        （注意 IDLE→LISTENING 本身是合法转移，但语义上不是打断）。
        """
        if self._current not in (EngineState.SPEAKING, EngineState.THINKING):
            return False
        return self.transition(EngineState.LISTENING)
