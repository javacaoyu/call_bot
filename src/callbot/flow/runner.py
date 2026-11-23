"""意图中枢状态机（WBS 6.3）：开场白 → 每轮「意图识别 → handler 回复」循环 → 结束语。

依赖注入全部异步回调（单测 fake；生产 6.3.3 接 webrtc/共享状态编排）：
- open_stream() -> AsyncIterator[str]：开场白口播流（直读或 6.2 双轨 LLM 兜底，
  由外部实现）；opening 节点 text 非空时直接 yield 文本、不调回调
- reply(handler_node, user_text, spoken_prefix=None) -> AsyncIterator[str]：
  handler 回复流；spoken_prefix 为打断上下文重建素材（打断轮的已说句子）；
  外部取消该流 = 打断，finally 保证状态回 awaiting，新转写可立即投递
- classify_fn(text) -> str | None：LLM 意图分类（关键词快路径由 runner 内建）
- on_end(text)：结束语回调（外部播报完成后挂断）

每轮语义：客户转写 → 关键词快路径 →（未命中）LLM 分类 → 路由 handler /
兜底边 / 结束边（连 end 节点的意图边 = 结束语义）。sticky 吸附：handler
sticky=true 时，未命中关键词的轮次跳过 LLM 分类直接留在本 handler。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from enum import StrEnum
from typing import Any

from callbot.flow.intent import IntentClassifier

logger = logging.getLogger(__name__)

FlowNode = dict[str, Any]


class FlowState(StrEnum):
    """流程状态机四态。"""

    INIT = "init"  # 未开场
    AWAITING = "awaiting"  # 等客户说话（每轮必经）
    REPLYING = "replying"  # 开场/回复进行中（打断窗口）
    ENDED = "ended"  # 已结束（输入忽略）


class FlowRunner:
    """意图中枢循环执行器（纯逻辑，IO 全部注入）。"""

    def __init__(
        self,
        definition: dict[str, Any],
        *,
        open_stream: Callable[[], AsyncIterator[str]] | None = None,
        reply: Callable[[FlowNode, str, str | None], AsyncIterator[str]] | None = None,
        classify_fn: Callable[[str], Awaitable[str | None]] | None = None,
        on_end: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._def = definition
        self._open_stream = open_stream
        self._reply = reply
        self._on_end = on_end
        self._nodes: dict[str, FlowNode] = {
            n["id"]: n for n in definition["nodes"]
        }
        self._edges: list[dict[str, Any]] = definition["edges"]

        self._opening = next(n for n in definition["nodes"] if n["type"] == "opening")
        self._intent_node = next(
            n for n in definition["nodes"] if n["type"] == "intent"
        )
        end_ids = {n["id"] for n in definition["nodes"] if n["type"] == "end"}

        # 意图出边：意图名 → 目标节点；不带 intent 的边 = 兜底
        self._intent_map: dict[str, str] = {}
        self._fallback_target: str | None = None
        intent_cfgs: list[dict[str, str]] = []
        for e in self._edges:
            if e["from"] != self._intent_node["id"]:
                continue
            cfg = e.get("intent")
            if cfg is None:
                self._fallback_target = e["to"]
            else:
                name = str(cfg["name"])
                self._intent_map[name] = e["to"]
                intent_cfgs.append(
                    {
                        "name": name,
                        "keywords": str(cfg.get("keywords", "")),
                        "description": str(cfg.get("description", "")),
                    }
                )
        # 结束语义：目标为 end 节点的意图边（名称可自定，语义由目标节点类型决定）
        self._end_intents = {
            name for name, target in self._intent_map.items() if target in end_ids
        }
        self._classifier = IntentClassifier(intent_cfgs, classify_fn)

        self._state = FlowState.INIT
        self._current_target: str | None = None  # 最近路由的 handler 目标（sticky 用）
        self._sticky_current = False

    @property
    def state(self) -> FlowState:
        """当前状态（外部可观测：前端画布高亮/日志）。"""
        return self._state

    async def start(self) -> AsyncIterator[str]:
        """执行开场白节点：text 非空直读；空则 open_stream() 兜底。"""
        if self._state is not FlowState.INIT:
            logger.info("start 被忽略: state=%s", self._state)
            return
        self._state = FlowState.REPLYING
        try:
            text = (self._opening.get("data") or {}).get("text", "")
            if text:
                yield text
            elif self._open_stream is not None:
                async for token in self._open_stream():
                    yield token
        finally:
            self._state = FlowState.AWAITING

    async def on_user_text(
        self,
        text: str,
        spoken_prefix: str | None = None,
    ) -> AsyncIterator[str]:
        """每轮客户转写：分类 → 路由 → 回复流；结束意图 → 结束语 + on_end。

        spoken_prefix：打断上下文重建素材，透传给 handler 回复回调。
        外部取消本生成器 = 打断；finally 保证状态回 awaiting。
        """
        if self._state is not FlowState.AWAITING:
            logger.info("on_user_text 被忽略: state=%s", self._state)
            return
        self._state = FlowState.REPLYING
        ended = False
        try:
            kw_hit = self._classifier.match_keywords(text)
            if self._sticky_current and kw_hit is None:
                # 吸附模式：未命中关键词 → 跳过 LLM 分类留在本 handler（追问节奏优化）
                target_id = self._current_target
            else:
                intent = kw_hit
                if intent is None:
                    intent = await self._classifier.classify(text)
                target_id = self._resolve_target(intent)
            if target_id is None:
                logger.warning("无兜底边，本轮不回复: %s", text)
                return
            node = self._nodes[target_id]
            if node["type"] == "end":
                end_text = str((node.get("data") or {}).get("text", "")).strip()
                logger.info("流程结束: %s", end_text or "(无结束语)")
                if end_text:
                    yield end_text
                ended = True
                self._state = FlowState.ENDED
                if self._on_end is not None:
                    await self._on_end(end_text)
                return
            # handler：记录路由（sticky 依据）→ 流式回复
            self._current_target = target_id
            self._sticky_current = bool((node.get("data") or {}).get("sticky", False))
            if self._reply is None:
                logger.warning("reply 未注入，跳过回复")
                return
            logger.info(
                "路由到 handler: %s（%s）",
                (node.get("data") or {}).get("name", node["id"]),
                node["id"],
            )
            async for token in self._reply(node, text, spoken_prefix):
                yield token
        finally:
            if not ended:
                self._state = FlowState.AWAITING

    def _resolve_target(self, intent: str | None) -> str | None:
        """意图 → 目标节点 id；None/未知 → 兜底边。"""
        if intent is not None and intent in self._intent_map:
            return self._intent_map[intent]
        return self._fallback_target
