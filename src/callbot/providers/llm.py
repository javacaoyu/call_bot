"""LLM Provider：OpenAI 兼容流式接口与 DeepSeek 实现。

设计要点（PRD 延迟优先 + 打断）：
- 流式逐 token 产出（首 token 即触发下游 TTS）；
- 关流 = 关闭异步生成器（生成器 finally 中关闭底层流），
  接入层取消生成任务即可停止 LLM 生成（3.3 打断基础）；
- 本地/云端切换 = 换 base_url + api_key + model（OpenAI 兼容全家桶）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# OpenAI 兼容消息格式：{"role": "system"|"user"|"assistant", "content": str}
ChatMessage = dict[str, str]

_DEFAULT_MAX_TOKENS = 256  # 外呼单轮回复短，PRD 建议 128~256


class StreamingLLM(Protocol):
    """流式 LLM Provider 接口（本地 / 云端实现均遵循）。"""

    def generate(
        self, messages: Sequence[ChatMessage], max_tokens: int = _DEFAULT_MAX_TOKENS
    ) -> AsyncIterator[str]:
        """流式生成回复文本，逐 token 产出；关闭生成器即停止生成。"""
        ...


class DeepSeekStreamingLLM:
    """DeepSeek（OpenAI 兼容）流式 LLM 客户端。"""

    def __init__(
        self,
        base_url: str = "https://api.deepseek.com",
        api_key: str = "",
        model: str = "deepseek-chat",
        client: Any = None,
    ) -> None:
        """Args:
            base_url: OpenAI 兼容端点（切 vLLM/Ollama 换这里）。
            api_key: API 密钥。
            model: 模型名。
            client: 测试注入用，缺省创建 AsyncOpenAI。
        """
        self._client = client or AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def generate(
        self, messages: Sequence[ChatMessage], max_tokens: int = _DEFAULT_MAX_TOKENS
    ) -> AsyncIterator[str]:
        """流式生成，逐 delta 产出文本 token。

        Yields:
            每个非空增量文本片段。
        """
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=list(messages),
            max_tokens=max_tokens,
            stream=True,
        )
        try:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            # 关流：生成器被关闭（打断）时确保底层 HTTP 流关闭
            await stream.close()
