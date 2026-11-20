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
