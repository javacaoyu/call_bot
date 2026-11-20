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
    """system prompt + 用户消息进 LLM；回复追加进历史。"""
    llm = FakeLLM(["你", "好"])
    orch = SimpleOrchestrator(llm=llm, system_prompt="sys")
    out = [t async for t in orch.stream_reply("hi")]
    assert out == ["你", "好"]
    assert llm.calls[0][0] == {"role": "system", "content": "sys"}
    assert llm.calls[0][1] == {"role": "user", "content": "hi"}
    # 第二轮：历史含上一轮 assistant 回复
    await orch.stream_reply("again").__anext__()
    msgs = llm.calls[1]
    assert msgs[-2] == {"role": "assistant", "content": "你好"}
    assert msgs[-1] == {"role": "user", "content": "again"}


async def test_simple_orchestrator_reset() -> None:
    """reset 清空历史。"""
    llm = FakeLLM(["好"])
    orch = SimpleOrchestrator(llm=llm)
    await orch.stream_reply("hi").__anext__()
    orch.reset()
    await orch.stream_reply("hi2").__anext__()
    assert len(llm.calls[1]) == 2  # 只剩 system + 新 user


def test_create_orchestrator_factory() -> None:
    """工厂按 kind 返回正确实现，未知 kind 报错。"""
    orch = create_orchestrator("simple", "u", "k", "m")
    assert isinstance(orch, SimpleOrchestrator)
    with pytest.raises(ValueError, match="未知编排后端"):
        create_orchestrator("nope", "u", "k", "m")


def test_agentscope_orchestrator_constructs() -> None:
    """AgentScope 实现可无网络构造（模型连接惰性）。"""
    orch = AgentScopeOrchestrator(
        base_url="https://api.deepseek.com",
        api_key="dummy",
        model="deepseek-chat",
    )
    assert orch._agent.name == "callbot"
