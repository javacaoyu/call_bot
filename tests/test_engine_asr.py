"""引擎 ASR 分块与回调单元测试（fake ASR，不进 GPU）。"""

from callbot.engine.engine import ConversationEngine
from callbot.engine.frames import AudioFrame
from callbot.providers.asr import ASRResult


class FakeASR:
    """记录每次调用与重置次数，返回可配置结果。"""

    def __init__(self) -> None:
        self.chunks: list[tuple[int, bool]] = []
        self.reset_calls = 0
        self.next_result: ASRResult | None = None

    def process_chunk(self, frame: AudioFrame, is_final: bool = False) -> ASRResult | None:
        self.chunks.append((len(frame.data), is_final))
        return self.next_result

    def reset(self) -> None:
        self.reset_calls += 1


def _make_frame(ms: int) -> AudioFrame:
    """生成指定毫秒数的静音帧（16k 单声道 PCM16）。"""
    samples = int(16000 * ms / 1000)
    return AudioFrame(data=b"\x00\x00" * samples)


def test_feed_accumulates_to_600ms_chunks() -> None:
    """30 帧 × 20ms 恰好拼成一块 600ms（19200 字节）送入 ASR。"""
    engine = ConversationEngine()
    asr = FakeASR()
    engine.attach_asr(asr)
    engine.start()
    for _ in range(30):
        engine.feed_audio(_make_frame(20))
    assert asr.chunks == [(19200, False)]


def test_feed_across_chunk_boundary() -> None:
    """31 帧 → 1 块送 ASR + 640 字节留在缓存。"""
    engine = ConversationEngine()
    asr = FakeASR()
    engine.attach_asr(asr)
    engine.start()
    for _ in range(31):
        engine.feed_audio(_make_frame(20))
    assert asr.chunks == [(19200, False)]
    assert len(engine._asr_buffer) == 640


def test_flush_sends_remainder_with_final() -> None:
    """flush 把剩余缓存补静音凑整 600ms，以 is_final=True 送入并重置 ASR。"""
    engine = ConversationEngine()
    asr = FakeASR()
    engine.attach_asr(asr)
    engine.start()
    for _ in range(10):
        engine.feed_audio(_make_frame(20))
    engine.flush_asr()
    assert asr.chunks == [(19200, True)]  # 6400 字节补零到整块
    assert asr.reset_calls == 1


def test_transcript_callback_fires() -> None:
    """ASR 返回文本时回调触发并携带结果。"""
    engine = ConversationEngine()
    asr = FakeASR()
    asr.next_result = ASRResult(text="你好", is_final=False)
    seen: list[ASRResult] = []
    engine.attach_asr(asr, seen.append)
    engine.start()
    for _ in range(30):
        engine.feed_audio(_make_frame(20))
    assert seen == [ASRResult(text="你好", is_final=False)]


def test_engine_without_asr_unchanged() -> None:
    """未挂 ASR 时 feed_audio 仅计数，行为与 2.3 一致。"""
    engine = ConversationEngine()
    engine.start()
    for _ in range(31):
        engine.feed_audio(_make_frame(20))
    assert engine.input_frame_count == 31
