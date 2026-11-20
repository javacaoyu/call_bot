"""编排层演示：一句话 → AgentScope 编排 → LLM 流式回复 + TTFT。

用法：uv run python scripts/orchestration_demo.py [用户输入]
需在 .env 配置 CALLBOT_LLM_API_KEY；CALLBOT_ORCHESTRATION_BACKEND 可切 simple。
"""

import asyncio
import sys
import time

from callbot.config import Settings
from callbot.orchestration.orchestrator import create_orchestrator


async def main() -> None:
    settings = Settings()
    if not settings.llm_api_key:
        print("未配置 API Key：请在 .env 中设置 CALLBOT_LLM_API_KEY")
        sys.exit(1)
    orch = create_orchestrator(
        kind=settings.orchestration_backend,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    text = sys.argv[1] if len(sys.argv) > 1 else "你好，我想了解一下你们的产品"

    print(f"编排后端 {settings.orchestration_backend} | 输入: {text}")
    t0 = time.perf_counter()
    first_token_at: float | None = None
    chars = 0
    async for token in orch.stream_reply(text):
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
