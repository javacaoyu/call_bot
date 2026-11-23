"""意图分类器（WBS 6.3）：关键词快路径 + AgentScope 结构化分类。

快路径：意图配置的 keywords（逗号分隔）本地子串匹配，零延迟；
未命中 → LLM 结构化分类（会话级缓存分类 Agent，独立状态防污染对话上下文）。
分类结果不在意图列表内 → None（走兜底边）；分类异常 → None + 日志（不炸通话）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class IntentResult(BaseModel):
    """意图分类结构化输出 schema（AgentScope structured_schema 用）。"""

    intent: str = Field(description="命中的意图名称，必须来自意图列表")


class IntentClassifier:
    """意图中枢的每轮分类器；classify_fn 可注入（单测 fake）。

    生产 classify_fn 用 build_agentscope_classify_fn 构造（AgentScope
    结构化分类，输出 IntentResult JSON）。
    """

    def __init__(
        self,
        intents: list[dict[str, str]],
        classify_fn: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        self._intents = [dict(i) for i in intents]
        self._names = {str(i["name"]) for i in self._intents}
        self._classify_fn = classify_fn

    def match_keywords(self, text: str) -> str | None:
        """关键词快路径：按意图声明顺序匹配，命中返回意图名（零延迟）。"""
        for intent in self._intents:
            for kw in str(intent.get("keywords", "")).split(","):
                kw = kw.strip()
                if kw and kw in text:
                    return str(intent["name"])
        return None

    async def classify(self, text: str) -> str | None:
        """完整分类：快路径 → LLM 结构化分类 → 归一/回退。"""
        hit = self.match_keywords(text)
        if hit is not None:
            return hit
        if self._classify_fn is None:
            return None
        try:
            name = await self._classify_fn(text)
        except Exception:  # noqa: BLE001 - 分类失败走兜底，不阻断通话
            logger.exception("意图分类失败，走兜底")
            return None
        if name is not None and name in self._names:
            return name
        if name is not None:
            logger.warning("分类结果不在意图列表，走兜底: %s", name)
        return None


def build_agentscope_classify_fn(
    intents: list[dict[str, str]],
    base_url: str,
    api_key: str,
    model: str,
) -> Callable[[str], Awaitable[str | None]]:
    """构造 AgentScope 结构化分类函数（会话级缓存分类 Agent）。

    分类 Agent 状态独立（不共享对话 AgentState——防意图 JSON 污染转写上下文）；
    意图列表描述构成稳定前缀（DeepSeek 上下文缓存友好）。
    """
    # 延迟导入：AgentScope 启动较重，仅云端分类路径需要
    from agentscope.agent import Agent
    from agentscope.credential import OpenAICredential
    from agentscope.message import Msg, TextBlock
    from agentscope.model import OpenAIChatModel

    intent_lines = "\n".join(
        f"- {i['name']}: {i.get('description', '')}" for i in intents
    )
    system_prompt = (
        "你是外呼对话的意图分类器。根据客户最近一句话判断其意图，"
        f"必须从以下意图中选择一个：\n{intent_lines}\n"
        '输出 JSON：{"intent": "意图名称"}'
    )
    credential = OpenAICredential(api_key=api_key, base_url=base_url)
    llm = OpenAIChatModel(credential=credential, model=model, stream=True)
    agent = Agent(name="intent_classifier", system_prompt=system_prompt, model=llm)

    async def classify(text: str) -> str | None:
        msg = Msg(name="user", role="user", content=[TextBlock(text=text)])
        final: Msg | None = None
        async for event in agent.reply_stream(
            inputs=msg,
            structured_schema=IntentResult,
            yield_final_msg=True,
        ):
            if isinstance(event, Msg):
                final = event
        if final is None:
            return None
        parsed = getattr(final, "structured_output", None)
        if isinstance(parsed, IntentResult):
            return parsed.intent
        logger.warning("结构化分类输出缺失，走兜底: %s", final)
        return None

    return classify
