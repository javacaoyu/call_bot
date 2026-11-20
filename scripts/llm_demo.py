"""LLM 流式演示：一句话提示 → 控制台流式打印 + TTFT 计时。

用法：uv run python scripts/llm_demo.py [提示词]
需在 .env 配置 CALLBOT_LLM_API_KEY（或环境变量）。
"""

import asyncio
import sys
import time

from callbot.config import Settings
from callbot.providers.llm import DeepSeekStreamingLLM


async def main() -> None:
    settings = Settings()
    if not settings.llm_api_key:
        print("未配置 API Key：请在 .env 中设置 CALLBOT_LLM_API_KEY")
        sys.exit(1)
    llm = DeepSeekStreamingLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    prompt = sys.argv[1] if len(sys.argv) > 1 else "用一句话介绍你自己"
    messages = [{"role": "user", "content": prompt}]

    print(f"模型 {settings.llm_model} | 提示: {prompt}")
    t0 = time.perf_counter()
    first_token_at: float | None = None
    chars = 0
    async for token in llm.generate(messages):
        if first_token_at is None:
            first_token_at = time.perf_counter()
        print(token, end="", flush=True)
        chars += len(token)
    total = time.perf_counter() - t0
    print()
    if first_token_at is not None:
        print(f"TTFT: {(first_token_at - t0) * 1000:.0f}ms | 总耗时: {total:.1f}s | {chars} 字符")


if __name__ == "__main__":
    asyncio.run(main())
