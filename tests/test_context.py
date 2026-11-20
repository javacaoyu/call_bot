"""上下文管控单元测试。"""

from callbot.orchestration.context import (
    HistoryManager,
    PromptBuilder,
    estimate_tokens,
    summarize_history,
)


def test_estimate_tokens() -> None:
    """字符数即 token 代理。"""
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("") == 0


def test_history_trim_drops_oldest() -> None:
    """超预算丢最旧轮。"""
    h = HistoryManager(max_tokens=10)
    h.add_user("a" * 8)
    h.add_assistant("b" * 8)  # 总量 16 > 10 → 丢第一轮
    assert [m["content"] for m in h.messages()] == ["b" * 8]


def test_history_trim_keeps_last_turn() -> None:
    """极端预算下保底留最后一轮。"""
    h = HistoryManager(max_tokens=5)
    h.add_user("a" * 10)
    h.add_assistant("b" * 10)
    msgs = h.messages()
    assert len(msgs) == 1
    assert msgs[0]["content"] == "b" * 10


def test_prompt_builder_order() -> None:
    """人设 → 合规边界 → 历史 → 当前输入，前缀稳定。"""
    b = PromptBuilder(system_prompt="人设", compliance_rules=["规则A"])
    msgs = b.build([{"role": "assistant", "content": "历史"}], "输入")
    assert msgs[0] == {"role": "system", "content": "人设"}
    assert msgs[1] == {"role": "system", "content": "合规边界：规则A"}
    assert msgs[2] == {"role": "assistant", "content": "历史"}
    assert msgs[-1] == {"role": "user", "content": "输入"}


class FakeLLM:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def generate(self, messages, max_tokens=256):  # noqa: ANN001
        for t in self._tokens:
            yield t


async def test_summarize_history() -> None:
    """摘要走 LLM 并拼接。"""
    llm = FakeLLM(["要点", "摘要"])
    out = await summarize_history([{"role": "user", "content": "你好"}], llm)
    assert out == "要点摘要"


async def test_summarize_empty() -> None:
    """空历史返回空串。"""
    assert await summarize_history([], FakeLLM([])) == ""
