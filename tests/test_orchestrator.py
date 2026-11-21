"""编排层单元测试（fake LLM / 无网络构造）。"""

import pytest

from callbot.orchestration.orchestrator import (
    AgentScopeOrchestrator,
    SimpleOrchestrator,
    create_orchestrator,
)
from callbot.providers.llm import ChatMessage


class FakeLLM:
    """记录调用消息并返回可配置流。"""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages, max_tokens=256):  # noqa: ANN001
        self.calls.append([dict(m) for m in messages])
        for t in self._tokens:
            yield t


async def test_simple_orchestrator_history() -> None:
    """稳定前缀 + 历史 + 当前输入进 LLM；回复追加进历史。"""
    llm = FakeLLM(["你", "好"])
    orch = SimpleOrchestrator(llm=llm, system_prompt="sys")
    out = [t async for t in orch.stream_reply("hi")]
    assert out == ["你", "好"]
    assert llm.calls[0][0] == {"role": "system", "content": "sys"}
    assert any("合规边界" in m["content"] for m in llm.calls[0])
    assert llm.calls[0][-1] == {"role": "user", "content": "hi"}
    # 第二轮：历史含上一轮 assistant 回复
    await orch.stream_reply("again").__anext__()
    msgs = llm.calls[1]
    assert msgs[-2] == {"role": "assistant", "content": "你好"}
    assert msgs[-1] == {"role": "user", "content": "again"}


async def test_simple_orchestrator_reset() -> None:
    """reset 清空历史（前缀保留）。"""
    llm = FakeLLM(["好"])
    orch = SimpleOrchestrator(llm=llm)
    await orch.stream_reply("hi").__anext__()
    orch.reset()
    await orch.stream_reply("hi2").__anext__()
    # 人设 + 3 条合规边界 + 新 user = 5 条，无历史
    assert len(llm.calls[1]) == 5


def test_create_orchestrator_factory() -> None:
    """工厂按 kind 返回正确实现，未知 kind 报错。"""
    orch = create_orchestrator("simple", "u", "k", "m")
    assert isinstance(orch, SimpleOrchestrator)
    with pytest.raises(ValueError, match="未知编排后端"):
        create_orchestrator("nope", "u", "k", "m")


async def test_simple_orchestrator_spoken_prefix() -> None:
    """打断上下文重建：已说句子以 assistant 身份注入历史（user 之前）。"""
    llm = FakeLLM(["新", "回复"])
    orch = SimpleOrchestrator(llm=llm, system_prompt="sys")
    out = [t async for t in orch.stream_reply("您说什么", spoken_prefix="第一句。第二句。")]
    assert out == ["新", "回复"]
    msgs = llm.calls[0]
    assert msgs[-2] == {"role": "assistant", "content": "第一句。第二句。"}
    assert msgs[-1] == {"role": "user", "content": "您说什么"}


async def test_simple_orchestrator_spoken_prefix_history_persists() -> None:
    """打断轮结束后：注入的已说句子与完整回复都在历史中延续。"""
    llm = FakeLLM(["好", "的"])
    orch = SimpleOrchestrator(llm=llm, system_prompt="sys")
    _ = [t async for t in orch.stream_reply("打断话", spoken_prefix="第一句。")]
    _ = [t async for t in orch.stream_reply("下一轮")]
    msgs = llm.calls[1]  # 下一轮视角
    assert msgs[-4] == {"role": "assistant", "content": "第一句。"}
    assert msgs[-3] == {"role": "user", "content": "打断话"}
    assert msgs[-2] == {"role": "assistant", "content": "好的"}
    assert msgs[-1] == {"role": "user", "content": "下一轮"}


def test_agentscope_orchestrator_constructs() -> None:
    """AgentScope 实现可无网络构造（模型连接惰性）。"""
    orch = AgentScopeOrchestrator(
        base_url="https://api.deepseek.com",
        api_key="dummy",
        model="deepseek-chat",
    )
    assert orch._agent.name == "callbot"


class _Evt:
    """伪 Agent 事件：TextBlockDeltaEvent 的 delta 文本。"""

    delta = "好的"


class FakeAgent:
    """伪 Agent：记录 observe 的消息与 reply_stream 调用。"""

    name = "callbot"

    def __init__(self) -> None:
        self.observed: list[object] = []

    async def observe(self, msgs=None) -> None:  # noqa: ANN001
        if msgs is not None:
            self.observed.append(msgs)

    async def reply_stream(self, inputs=None, **kwargs):  # noqa: ANN001, ANN002
        yield _Evt()


async def test_agentscope_spoken_prefix_observes_assistant() -> None:
    """打断上下文重建：已说句子 observe 为 assistant 消息后触发回复。"""
    orch = AgentScopeOrchestrator(base_url="x", api_key="k", model="m")
    orch._agent = FakeAgent()  # noqa: SLF001 - 注入伪 Agent
    out = [t async for t in orch.stream_reply("用户新话", spoken_prefix="已说句子。")]
    assert out == ["好的"]
    (msg,) = orch._agent.observed
    assert msg.role == "assistant"
    assert msg.content[0].text == "已说句子。"


async def test_agentscope_empty_prefix_no_observe() -> None:
    """无打断时行为不变：不 observe 额外消息。"""
    orch = AgentScopeOrchestrator(base_url="x", api_key="k", model="m")
    orch._agent = FakeAgent()  # noqa: SLF001
    out = [t async for t in orch.stream_reply("hi")]
    assert out == ["好的"]
    assert orch._agent.observed == []


async def test_simple_interrupted_with_zero_spoken_injects_placeholder() -> None:
    """打断轮且已说 0 句：注入占位 assistant，保持 user→assistant 形态。"""
    llm = FakeLLM(["好"])
    orch = SimpleOrchestrator(llm=llm, system_prompt="sys")
    _ = [t async for t in orch.stream_reply("新问题", spoken_prefix="")]
    msgs = llm.calls[0]
    assert msgs[-2] == {"role": "assistant", "content": "（上一句回复被打断）"}
    assert msgs[-1] == {"role": "user", "content": "新问题"}


async def test_simple_normal_turn_no_placeholder() -> None:
    """正常轮（None）不注入占位。"""
    llm = FakeLLM(["好"])
    orch = SimpleOrchestrator(llm=llm, system_prompt="sys")
    _ = [t async for t in orch.stream_reply("你好")]
    roles = [m["role"] for m in llm.calls[0]]
    assert roles.count("assistant") == 0  # 首轮正常无 assistant 历史


async def test_agentscope_interrupted_zero_spoken_placeholder() -> None:
    """AgentScope：打断轮空串也 observe 占位 assistant。"""
    orch = AgentScopeOrchestrator(base_url="x", api_key="k", model="m")
    orch._agent = FakeAgent()  # noqa: SLF001
    _ = [t async for t in orch.stream_reply("新问题", spoken_prefix="")]
    (msg,) = orch._agent.observed
    assert msg.role == "assistant"
    assert msg.content[0].text == "（上一句回复被打断）"
