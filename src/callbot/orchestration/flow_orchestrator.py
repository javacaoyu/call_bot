"""流程编排层（WBS 6.3）：共享状态 + 按 handler 节点路由。

共享状态 = 一次外呼一个 AgentState（AgentScope）或共享 HistoryManager（自建回退）；
每个 handler 节点一个智能体实例（system prompt = 节点话术渲染值），全部注入共享
记忆——路由切换零成本：新节点直接读共享上下文（含其他节点已说的话）。
打断轮 spoken_prefix 以 assistant 身份 observe 进共享状态，所有节点可见。

双实现（配置驱动）：AgentScope（含工具调用）/ Simple 自建回退（不支持工具）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from callbot.orchestration.context import (
    INTERRUPTED_PLACEHOLDER,
    HistoryManager,
    PromptBuilder,
)
from callbot.providers.llm import ChatMessage, DeepSeekStreamingLLM

logger = logging.getLogger(__name__)

HandlerNode = dict[str, Any]
Toolkit = Any  # agentscope.tool.Toolkit（延迟导入）


class FlowOrchestrator(Protocol):
    """6.3 流程编排层接口：纯文字进出，按 handler 节点路由。"""

    def stream_handler_reply(
        self,
        node: HandlerNode,
        user_text: str,
        spoken_prefix: str | None = None,
    ) -> AsyncIterator[str]:
        """handler 节点流式回复；关闭生成器即停止生成（打断）。"""
        ...

    def stream_opening(self, user_text: str, system_prompt: str) -> AsyncIterator[str]:
        """开场 LLM 兜底：以人设 prompt 生成开场白（进入共享状态）。"""
        ...

    def reset(self) -> None:
        """清空会话状态。"""
        ...


class AgentScopeFlowOrchestrator:
    """AgentScope 实现：共享 AgentState + per-node Agent 缓存 + 工具注入。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        resolve_prompt: Callable[[HandlerNode], str],
        tool_resolver: Callable[[list[str]], Toolkit | None] | None = None,
    ) -> None:
        # 延迟导入：AgentScope 启动较重，仅该实现需要
        from agentscope.agent import Agent
        from agentscope.credential import OpenAICredential
        from agentscope.model import OpenAIChatModel
        from agentscope.state import AgentState

        self._Agent = Agent
        self._credential = OpenAICredential(api_key=api_key, base_url=base_url)
        self._model_name = model
        self._OpenAIChatModel = OpenAIChatModel
        self._Msg = None  # 惰性取（见 _message_types）
        self._TextBlock = None
        self._state = AgentState()  # 共享状态：一次外呼一个
        self._agents: dict[str, Any] = {}
        self._opening_agent: Any | None = None
        self._resolve_prompt = resolve_prompt
        self._tool_resolver = tool_resolver

    def _message_types(self) -> tuple[Any, Any]:
        from agentscope.message import Msg, TextBlock

        if self._Msg is None:
            self._Msg, self._TextBlock = Msg, TextBlock
        return self._Msg, self._TextBlock

    def _new_model(self) -> Any:
        return self._OpenAIChatModel(
            credential=self._credential, model=self._model_name, stream=True
        )

    async def _agent_for(self, node: HandlerNode) -> Any:
        """按节点取/建 Agent：全部注入共享 state；system prompt = 节点话术渲染值。"""
        node_id = node["id"]
        agent = self._agents.get(node_id)
        if agent is None:
            toolkit = None
            tool_ids = (node.get("data") or {}).get("tool_ids", [])
            if tool_ids and self._tool_resolver is not None:
                toolkit = await self._tool_resolver(list(tool_ids))
            agent = self._Agent(
                name=f"handler_{node_id}",
                system_prompt=self._resolve_prompt(node),
                model=self._new_model(),
                state=self._state,
                toolkit=toolkit,
            )
            self._agents[node_id] = agent
            logger.info("handler Agent 已创建: %s", node_id)
        return agent

    async def stream_handler_reply(
        self,
        node: HandlerNode,
        user_text: str,
        spoken_prefix: str | None = None,
    ) -> AsyncIterator[str]:
        """Agent 流式回复：打断轮 spoken_prefix observe 进共享状态。"""
        Msg, TextBlock = self._message_types()
        agent = await self._agent_for(node)
        if spoken_prefix is not None:
            await agent.observe(
                Msg(
                    name="assistant",
                    role="assistant",
                    content=[TextBlock(text=spoken_prefix or INTERRUPTED_PLACEHOLDER)],
                ),
            )
        async for event in agent.reply_stream(
            inputs=Msg(
                name="user",
                role="user",
                content=[TextBlock(text=user_text)],
            ),
        ):
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                yield delta

    async def stream_opening(self, user_text: str, system_prompt: str) -> AsyncIterator[str]:
        """开场 LLM 兜底：专用 opening Agent（共享状态，人设 prompt）。"""
        Msg, TextBlock = self._message_types()
        if self._opening_agent is None:
            self._opening_agent = self._Agent(
                name="opening",
                system_prompt=system_prompt,
                model=self._new_model(),
                state=self._state,
            )
        async for event in self._opening_agent.reply_stream(
            inputs=Msg(
                name="user",
                role="user",
                content=[TextBlock(text=user_text)],
            ),
        ):
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                yield delta

    def reset(self) -> None:
        """清空共享状态：清缓存 Agent（下次路由重建）并换新 AgentState。"""
        self._agents.clear()
        self._opening_agent = None
        self._state = type(self._state)()


class SimpleFlowOrchestrator:
    """自建回退实现：共享 HistoryManager（共享状态语义）+ per-node PromptBuilder。

    不支持工具调用（ReAct 需 AgentScope）；绑定工具时记警告，6.4 补执行。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        resolve_prompt: Callable[[HandlerNode], str],
    ) -> None:
        self._llm = DeepSeekStreamingLLM(base_url=base_url, api_key=api_key, model=model)
        self._history = HistoryManager()  # 共享历史：跨节点连续
        self._builders: dict[str, PromptBuilder] = {}
        self._opening_builder: PromptBuilder | None = None
        self._resolve_prompt = resolve_prompt

    def _builder_for(self, node: HandlerNode) -> PromptBuilder:
        node_id = node["id"]
        builder = self._builders.get(node_id)
        if builder is None:
            builder = PromptBuilder(system_prompt=self._resolve_prompt(node))
            self._builders[node_id] = builder
        return builder

    async def _stream_with_builder(
        self,
        builder: PromptBuilder,
        user_text: str,
    ) -> AsyncIterator[str]:
        """组装消息 → 流式生成 → 记录共享历史。"""
        messages: list[ChatMessage] = builder.build(self._history.messages(), user_text)
        pieces: list[str] = []
        async for token in self._llm.generate(messages):
            pieces.append(token)
            yield token
        self._history.add_user(user_text)
        self._history.add_assistant("".join(pieces))

    async def stream_handler_reply(
        self,
        node: HandlerNode,
        user_text: str,
        spoken_prefix: str | None = None,
    ) -> AsyncIterator[str]:
        """handler 回复：打断轮 spoken_prefix 以 assistant 身份入共享历史。"""
        tool_ids = (node.get("data") or {}).get("tool_ids", [])
        if tool_ids:
            logger.warning(
                "Simple 编排不支持工具调用（节点 %s 绑定 %d 个工具）",
                node["id"],
                len(tool_ids),
            )
        if spoken_prefix is not None:
            self._history.add_assistant(spoken_prefix or INTERRUPTED_PLACEHOLDER)
        async for token in self._stream_with_builder(self._builder_for(node), user_text):
            yield token

    async def stream_opening(self, user_text: str, system_prompt: str) -> AsyncIterator[str]:
        """开场 LLM 兜底：人设 prompt 的专用 builder（共享历史）。"""
        if self._opening_builder is None:
            self._opening_builder = PromptBuilder(system_prompt=system_prompt)
        async for token in self._stream_with_builder(self._opening_builder, user_text):
            yield token

    def reset(self) -> None:
        """清空共享历史。"""
        self._history.reset()
        self._builders.clear()
        self._opening_builder = None


def create_flow_orchestrator(
    kind: str,
    base_url: str,
    api_key: str,
    model: str,
    resolve_prompt: Callable[[HandlerNode], str],
    tool_resolver: Callable[[list[str]], Toolkit | None] | None = None,
) -> FlowOrchestrator:
    """配置驱动的流程编排层工厂（agentscope / simple）。"""
    if kind == "agentscope":
        return AgentScopeFlowOrchestrator(
            base_url=base_url,
            api_key=api_key,
            model=model,
            resolve_prompt=resolve_prompt,
            tool_resolver=tool_resolver,
        )
    if kind == "simple":
        return SimpleFlowOrchestrator(
            base_url=base_url,
            api_key=api_key,
            model=model,
            resolve_prompt=resolve_prompt,
        )
    raise ValueError(f"未知编排后端: {kind}")
