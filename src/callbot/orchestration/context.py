"""上下文管控：稳定前缀（Prompt 缓存友好）+ 历史滑窗 + 摘要压缩。

延迟优先（PRD 5.2）：系统人设/合规边界固定前置，命中 DeepSeek 上下文缓存；
历史超预算按滑窗裁剪，必要时用 LLM 摘要压缩。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from callbot.providers.llm import ChatMessage

logger = logging.getLogger(__name__)

DEFAULT_MAX_HISTORY_TOKENS = 2000
DEFAULT_SYSTEM_PROMPT = "你是一名专业的外呼机器人客服，回答简洁、礼貌、口语化。"
_COMPLIANCE_RULES = [
    "不做虚假承诺，不夸大产品效果",
    "不索要银行卡密码等敏感信息",
    "不发表违规话术，遵守外呼合规要求",
]


def estimate_tokens(text: str) -> int:
    """token 数代理：中文字符 ≈ 1 token。

    不用 tiktoken：其 BPE 词表下载源（openaipublic）在国内网络常被墙。
    """
    return len(text)


class HistoryManager:
    """对话历史管理：token 预算滑窗裁剪（丢最旧轮，保底留最后一轮）。"""

    def __init__(self, max_tokens: int = DEFAULT_MAX_HISTORY_TOKENS) -> None:
        self._max_tokens = max_tokens
        self._turns: list[ChatMessage] = []

    def add_user(self, text: str) -> None:
        """追加用户消息。"""
        self._turns.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        """追加机器人回复。"""
        self._turns.append({"role": "assistant", "content": text})

    def messages(self) -> list[ChatMessage]:
        """返回预算内的历史（按时间顺序，最旧优先裁剪）。"""
        keep = list(self._turns)
        total = sum(estimate_tokens(m["content"]) for m in keep)
        while total > self._max_tokens and len(keep) > 1:
            total -= estimate_tokens(keep[0]["content"])
            keep = keep[1:]
        return keep

    @property
    def turn_count(self) -> int:
        """已记录轮数（未裁剪）。"""
        return len(self._turns)

    def reset(self) -> None:
        """清空历史。"""
        self._turns.clear()


class PromptBuilder:
    """稳定前缀 + 变化内容组装。

    前缀（人设 + 合规边界）保持字节级稳定 → DeepSeek 上下文缓存命中；
    变化内容（历史 + 当前输入）全部靠后。
    """

    def __init__(
        self,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        compliance_rules: Sequence[str] = _COMPLIANCE_RULES,
    ) -> None:
        self._system_prompt = system_prompt
        self._compliance_rules = list(compliance_rules)

    def build(self, history: Sequence[ChatMessage], user_text: str) -> list[ChatMessage]:
        """组装完整消息列表：人设 → 合规边界 → 历史 → 当前输入。"""
        messages: list[ChatMessage] = [
            {"role": "system", "content": self._system_prompt}
        ]
        for rule in self._compliance_rules:
            messages.append({"role": "system", "content": f"合规边界：{rule}"})
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return messages


async def summarize_history(turns: Sequence[ChatMessage], llm: Any) -> str:
    """用 LLM 把历史压缩成一句话摘要（被滑窗丢弃的旧轮可替换为摘要）。"""
    if not turns:
        return ""
    dialogue = "\n".join(f"{m['role']}: {m['content']}" for m in turns)
    pieces: list[str] = []
    async for token in llm.generate(
        [
            {"role": "system", "content": "你是对话摘要助手，用一句话概括对话要点。"},
            {"role": "user", "content": dialogue},
        ],
        max_tokens=100,
    ):
        pieces.append(token)
    return "".join(pieces).strip()
