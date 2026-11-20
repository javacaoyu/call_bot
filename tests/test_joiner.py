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


def test_split_chinese_pause_punct() -> None:
    """顿号逗号冒号均切分。"""
    assert split_segment("abcd、efg", 20) == ("abcd、", "efg")
    assert split_segment("ab，cd", 20) == ("ab，", "cd")
    assert split_segment("ab：cd", 20) == ("ab：", "cd")


def test_split_english_punct() -> None:
    """英文逗号分号冒号切分；句点后接空格才切。"""
    assert split_segment("ab, cd", 20) == ("ab,", " cd")
    assert split_segment("ab; cd", 20) == ("ab;", " cd")
    assert split_segment("ab: cd", 20) == ("ab:", " cd")


def test_split_dot_guards_decimals() -> None:
    """小数点/缩写不切断；句尾句点切分。"""
    assert split_segment("3.5折优惠", 20) == ("", "3.5折优惠")
    assert split_segment("好的. 下一步", 20) == ("好的.", " 下一步")


def test_split_ellipsis() -> None:
    """省略号切分。"""
    assert split_segment("这个……那个", 20) == ("这个…", "…那个")


async def test_joiner_segments_by_punctuation() -> None:
    """按标点分段合成（逗号顿号均切），尾段 flush。"""
    tts = FakeTTS()
    joiner = SpeechJoiner(tts)
    frames = [f async for f in joiner.run(_tokens("你好", "，我是", "助手。", "请问"))]
    assert tts.synthesized == ["你好，", "我是助手。", "请问"]
    assert len(frames) == 3


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


async def test_joiner_skips_newline_only_segments() -> None:
    """LLM 列表格式（：后换行）的纯换行段跳过，不送 TTS。"""
    tts = FakeTTS()
    joiner = SpeechJoiner(tts)
    frames = [f async for f in joiner.run(_tokens("主要分这几块：\n", "\n第一点"))]
    assert tts.synthesized == ["主要分这几块：", "第一点"]
    assert len(frames) == 2
