"""对话编排层：纯文字进出（转写 → 编排 → LLM → 回复文本）。

接口隔离：AgentScope 编排与自建 fallback 双实现，配置驱动切换
（CLAUDE.md 约定：AgentScope 只做纯文字编排，可回退自建）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from callbot.orchestration.context import (
    DEFAULT_MAX_HISTORY_TOKENS,
    DEFAULT_SYSTEM_PROMPT,
    HistoryManager,
    PromptBuilder,
)
from callbot.providers.llm import ChatMessage, DeepSeekStreamingLLM

logger = logging.getLogger(__name__)


# 打断轮且已说 0 句时的 assistant 占位：保持历史形态（user→assistant→user），
# 否则模型看到连续多条 user 消息无人回复，会逐个补答历史问题
_INTERRUPTED_PLACEHOLDER = "（上一句回复被打断）"


class Orchestrator(Protocol):
    """编排层接口（纯文字进、纯文字出）。"""

    def stream_reply(
        self, user_text: str, spoken_prefix: str | None = None
    ) -> AsyncIterator[str]:
        """根据用户文本流式生成回复；关闭生成器即停止生成。

        spoken_prefix：打断上下文重建（3.3）——打断轮的下一轮传入机器人
        「已完整说出的句子」（可为空串，此时注入占位 assistant 消息）；
        正常轮次为 None（不注入）。
        """
        ...

    def reset(self) -> None:
        """清空会话历史。"""
        ...


class SimpleOrchestrator:
    """自建 fallback 编排：稳定前缀 + 历史滑窗 + 自有流式 LLM。"""

    def __init__(
        self,
        llm: DeepSeekStreamingLLM,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_history_tokens: int = DEFAULT_MAX_HISTORY_TOKENS,
    ) -> None:
        self._llm = llm
        self._builder = PromptBuilder(system_prompt=system_prompt)
        self._history = HistoryManager(max_tokens=max_history_tokens)

    async def stream_reply(
        self, user_text: str, spoken_prefix: str | None = None
    ) -> AsyncIterator[str]:
        """组装消息 → 流式生成 → 记录历史。

        打断上下文重建：spoken_prefix 非 None（打断轮）时先以 assistant
        身份入历史——已说 0 句则注入占位，保持 user→assistant 形态。
        """
        if spoken_prefix is not None:
            self._history.add_assistant(spoken_prefix or _INTERRUPTED_PLACEHOLDER)
        messages: Sequence[ChatMessage] = self._builder.build(
            self._history.messages(), user_text
        )
        pieces: list[str] = []
        async for token in self._llm.generate(messages):
            pieces.append(token)
            yield token
        self._history.add_user(user_text)
        self._history.add_assistant("".join(pieces))

    def reset(self) -> None:
        """清空历史（前缀保留）。"""
        self._history.reset()


class AgentScopeOrchestrator:
    """AgentScope 编排实现：Agent + OpenAIChatModel（OpenAI 兼容端点）。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        # 延迟导入：AgentScope 启动较重，仅该实现需要
        from agentscope.agent import Agent
        from agentscope.credential import OpenAICredential
        from agentscope.model import OpenAIChatModel

        credential = OpenAICredential(api_key=api_key, base_url=base_url)
        llm = OpenAIChatModel(credential=credential, model=model, stream=True)
        self._agent = Agent(name="callbot", system_prompt=system_prompt, model=llm)

    async def stream_reply(
        self, user_text: str, spoken_prefix: str | None = None
    ) -> AsyncIterator[str]:
        """Agent 流式回复：取 TextBlockDeltaEvent 的 delta 文本。

        打断上下文重建：spoken_prefix 非 None（打断轮）时先 observe 一条
        assistant 消息（已完整说出的句子；空则占位），保持历史形态。
        """
        from agentscope.message import Msg, TextBlock

        if spoken_prefix is not None:
            await self._agent.observe(
                Msg(
                    name="assistant",
                    role="assistant",
                    content=[TextBlock(text=spoken_prefix or _INTERRUPTED_PLACEHOLDER)],
                ),
            )
        async for event in self._agent.reply_stream(
            inputs=Msg(
                name="user",
                role="user",
                content=[TextBlock(text=user_text)],
            ),
        ):
            # TextBlockDeltaEvent 的文本增量在 delta 字段
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                yield delta

    def reset(self) -> None:
        """清空会话历史。"""
        self._agent.observe()  # 无参 observe 即重置（AgentScope 语义）


def create_orchestrator(
    kind: str,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> Orchestrator:
    """配置驱动的编排层工厂。

    Args:
        kind: "agentscope" 或 "simple"（自建 fallback）。
        base_url / api_key / model: OpenAI 兼容端点配置。
        system_prompt: 系统人设。

    Returns:
        对应实现；未知 kind 抛出 ValueError。
    """
    if kind == "agentscope":
        return AgentScopeOrchestrator(
            base_url=base_url,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
        )
    if kind == "simple":
        return SimpleOrchestrator(
            llm=DeepSeekStreamingLLM(base_url=base_url, api_key=api_key, model=model),
            system_prompt=system_prompt,
        )
    raise ValueError(f"未知编排后端: {kind}")
