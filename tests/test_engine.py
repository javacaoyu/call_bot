"""语音引擎骨架单元测试。"""

from callbot.engine.engine import ConversationEngine
from callbot.engine.frames import AudioFrame, frame_duration_ms
from callbot.engine.state import EngineState, StateMachine


def test_frame_duration_ms() -> None:
    """800 样本 @16k = 50ms。"""
    frame = AudioFrame(data=b"\x00\x00" * 800, sample_rate=16000)
    assert frame_duration_ms(frame) == 50


def test_state_machine_valid_transition() -> None:
    """IDLE → LISTENING 合法。"""
    sm = StateMachine()
    assert sm.transition(EngineState.LISTENING) is True
    assert sm.current is EngineState.LISTENING


def test_state_machine_invalid_transition() -> None:
    """SPEAKING 不能直接 THINKING，状态应保持不变。"""
    sm = StateMachine()
    assert sm.transition(EngineState.SPEAKING) is True  # 开场白：IDLE → SPEAKING 合法
    assert sm.transition(EngineState.THINKING) is False
    assert sm.current is EngineState.SPEAKING


def test_state_machine_closed_terminal() -> None:
    """CLOSED 为终态，不可再转移。"""
    sm = StateMachine(initial=EngineState.CLOSED)
    assert sm.transition(EngineState.IDLE) is False


def test_state_machine_callback() -> None:
    """转移成功应触发回调并携带前后状态。"""
    sm = StateMachine()
    seen: list[tuple[EngineState, EngineState]] = []
    sm.on_change(lambda frm, to: seen.append((frm, to)))
    sm.transition(EngineState.LISTENING)
    assert seen == [(EngineState.IDLE, EngineState.LISTENING)]


def test_engine_mark_thinking() -> None:
    """听 → 想 的显式转移。"""
    engine = ConversationEngine()
    engine.start()
    engine.mark_thinking()
    assert engine.state is EngineState.THINKING


def test_engine_feed_count() -> None:
    """输入帧计数递增。"""
    engine = ConversationEngine()
    engine.start()
    engine.feed_audio(AudioFrame(data=b"\x00\x00" * 160))
    engine.feed_audio(AudioFrame(data=b"\x00\x00" * 160))
    assert engine.input_frame_count == 2


def test_engine_output_fifo_and_state() -> None:
    """输出 FIFO 顺序正确；队列取空后 SPEAKING 回到 LISTENING。"""
    engine = ConversationEngine()
    engine.start()
    f1 = AudioFrame(data=b"\x00\x00" * 160)
    f2 = AudioFrame(data=b"\x01\x01" * 160)
    engine.enqueue_output(f1)
    engine.enqueue_output(f2)
    assert engine.state is EngineState.SPEAKING
    assert engine.get_output_frame() is f1
    assert engine.get_output_frame() is f2
    assert engine.get_output_frame() is None
    assert engine.state is EngineState.LISTENING


def test_engine_stop() -> None:
    """停止后进入 CLOSED，输入帧被忽略。"""
    engine = ConversationEngine()
    engine.start()
    engine.stop()
    assert engine.state is EngineState.CLOSED
    engine.feed_audio(AudioFrame(data=b"\x00\x00" * 160))
    assert engine.input_frame_count == 0


def test_state_machine_enter_exit_callbacks() -> None:
    """转移成功依次触发 exit(旧态) → change → enter(新态)；非法转移不触发。"""
    sm = StateMachine()
    events: list[str] = []
    sm.on_exit(lambda: events.append("exit"))
    sm.on_change(lambda frm, to: events.append(f"change:{frm.name}->{to.name}"))
    sm.on_enter(lambda: events.append("enter"))
    assert sm.transition(EngineState.LISTENING) is True
    assert events == ["exit", "change:IDLE->LISTENING", "enter"]
    events.clear()
    assert sm.transition(EngineState.LISTENING) is False  # 自转移非法
    assert events == []


def test_state_machine_interrupt_from_speaking() -> None:
    """SPEAKING 中 interrupt 回 LISTENING 并返回 True。"""
    sm = StateMachine()
    sm.transition(EngineState.SPEAKING)  # IDLE → SPEAKING（开场白）
    assert sm.interrupt() is True
    assert sm.current is EngineState.LISTENING


def test_state_machine_interrupt_from_thinking() -> None:
    """THINKING 中 interrupt 回 LISTENING（LLM 生成中被抢话）。"""
    sm = StateMachine()
    sm.transition(EngineState.LISTENING)
    sm.transition(EngineState.THINKING)
    assert sm.interrupt() is True
    assert sm.current is EngineState.LISTENING


def test_state_machine_interrupt_invalid_states() -> None:
    """IDLE/LISTENING/CLOSED 中 interrupt 失败且状态不变。"""
    for initial, name in [
        (EngineState.IDLE, "IDLE"),
        (EngineState.LISTENING, "LISTENING"),
        (EngineState.CLOSED, "CLOSED"),
    ]:
        sm = StateMachine(initial=initial)
        assert sm.interrupt() is False, name
        assert sm.current is initial, name


def test_engine_spoken_segments_confirmed_on_boundary() -> None:
    """段尾帧出队确认该段「已完整说出」；自然说完 spoken 清空。"""
    engine = ConversationEngine()
    engine.start()
    f1, f2, f3 = (AudioFrame(data=b"\x00\x00" * 160) for _ in range(3))
    engine.enqueue_output(f1, "第一句。")  # 段 A：2 帧
    engine.enqueue_output(f2, "第一句。")
    engine.enqueue_output(f3, "第二句。")  # 段 B：1 帧
    assert engine.get_output_frame() is f1  # 非段尾，不确认
    assert engine.get_output_frame() is f2  # 段尾（下一帧文本不同）→ 确认 A
    assert engine.get_output_frame() is f3  # 段尾（队列空）→ 确认 B 后自然清空
    assert engine.interrupt() == []  # 自然说完，无 spoken 快照


def test_engine_interrupt_returns_spoken_and_discards_rest() -> None:
    """打断：已完整说出的段保留，未播出/半句丢弃，状态回 LISTENING。"""
    engine = ConversationEngine()
    engine.start()
    f1, f2, f3 = (AudioFrame(data=b"\x00\x00" * 160) for _ in range(3))
    engine.enqueue_output(f1, "第一句。")
    engine.enqueue_output(f2, "第一句。")
    engine.enqueue_output(f3, "第二句。")  # 段 B 未开始播
    engine.get_output_frame()
    engine.get_output_frame()  # 段 A 说完
    spoken = engine.interrupt()  # 段 B 在队中被丢弃
    assert spoken == ["第一句。"]
    assert engine.get_output_frame() is None  # 队列已清空
    assert engine.state is EngineState.LISTENING


def test_engine_interrupt_half_segment_discarded() -> None:
    """打断时正在播的半句不算「已完整说出」。"""
    engine = ConversationEngine()
    engine.start()
    engine.enqueue_output(AudioFrame(data=b"\x00\x00" * 160), "半句话。")
    engine.enqueue_output(AudioFrame(data=b"\x00\x00" * 160), "半句话。")
    engine.get_output_frame()  # 只播了段首帧，段未完整
    assert engine.interrupt() == []
    assert engine.state is EngineState.LISTENING


def test_engine_interrupt_noop_outside_speaking() -> None:
    """LISTENING 下 interrupt 无副作用；CLOSED 后同样。"""
    engine = ConversationEngine()
    engine.start()  # LISTENING
    assert engine.interrupt() == []
    assert engine.state is EngineState.LISTENING
    engine.stop()
    assert engine.interrupt() == []
    assert engine.state is EngineState.CLOSED
