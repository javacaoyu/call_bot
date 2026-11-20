"""流式衔接器单元测试（fake TTS / fake token 流）。"""

from callbot.engine.frames import AudioFrame
from callbot.engine.joiner import SpeechJoiner, split_segment


class FakeTTS:
    """记录每次合成调用，返回一块固定帧。"""

    def __init__(self) -> None:
        self.synthesized: list[str] = []

    async def synthesize(
        self, text: str, instruct_text: str = "", prompt_wav: str = "", speed: float = 1.0
    ):
        self.synthesized.append(text)
        yield AudioFrame(data=b"\x00\x00" * 100)


async def _tokens(*parts: str):
    for p in parts:
        yield p


def test_split_by_punctuation() -> None:
    """句末标点触发切分（含标点）。"""
    assert split_segment("你好。后面", 20) == ("你好。", "后面")
    assert split_segment("你好！", 20) == ("你好！", "")
    assert split_segment("你好", 20) == ("", "你好")


def test_split_by_threshold() -> None:
    """无标点达到 max_chars 也切。"""
    assert split_segment("x" * 20 + "y", 20) == ("x" * 20, "y")


async def test_joiner_segments_by_punctuation() -> None:
    """按标点分段合成，尾段 flush。"""
    tts = FakeTTS()
    joiner = SpeechJoiner(tts)
    frames = [f async for f in joiner.run(_tokens("你好", "，我是", "助手。", "请问"))]
    assert tts.synthesized == ["你好，我是助手。", "请问"]
    assert len(frames) == 2


async def test_joiner_threshold_without_punctuation() -> None:
    """无标点长文本按阈值分段。"""
    tts = FakeTTS()
    joiner = SpeechJoiner(tts, max_chars=5)
    frames = [f async for f in joiner.run(_tokens("123456789"))]
    assert tts.synthesized == ["12345", "6789"]
    assert len(frames) == 2


async def test_joiner_empty_tail_not_synthesized() -> None:
    """尾部纯空白不触发合成。"""
    tts = FakeTTS()
    joiner = SpeechJoiner(tts)
    frames = [f async for f in joiner.run(_tokens("好的。"))]
    assert tts.synthesized == ["好的。"]
    assert len(frames) == 1
