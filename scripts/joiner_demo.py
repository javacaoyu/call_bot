"""衔接器演示：真实 LLM → SpeechJoiner → 真实 TTS。

日志可见「首 token 即合成」效果：LLM token 流出的同时，句段触发 TTS。
输出 wav 供试听：recordings/joiner_demo.wav

用法：uv run python scripts/joiner_demo.py [问题]
前置：CALLBOT_LLM_API_KEY（.env）+ LD_LIBRARY_PATH（见 CLAUDE.md）。
"""

import asyncio
import sys
import time
import wave
from collections.abc import AsyncIterator

from callbot.config import Settings
from callbot.engine.frames import AudioFrame
from callbot.engine.joiner import SpeechJoiner
from callbot.orchestration.orchestrator import create_orchestrator
from callbot.providers.tts import CosyVoice2StreamingTTS


class TimingTTS(CosyVoice2StreamingTTS):
    """包装 TTS 打印每段合成触发时机。"""

    def __init__(self, t0: float) -> None:
        super().__init__()
        self._t0 = t0

    async def synthesize(
        self, text: str, instruct_text: str = "", prompt_wav: str = "", speed: float = 1.0
    ) -> AsyncIterator[AudioFrame]:
        print(f"[TTS 触发 +{time.perf_counter() - self._t0:.2f}s] {text}")
        async for frame in super().synthesize(text, instruct_text, prompt_wav, speed):
            yield frame


async def main() -> None:
    settings = Settings()
    if not settings.llm_api_key:
        print("未配置 API Key：请在 .env 中设置 CALLBOT_LLM_API_KEY")
        sys.exit(1)
    text = sys.argv[1] if len(sys.argv) > 1 else "你好，请介绍一下你们的外呼机器人产品有哪些功能"
    print(f"问题: {text}")

    orch = create_orchestrator(
        kind=settings.orchestration_backend,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    t0 = time.perf_counter()
    tts = TimingTTS(t0)
    await asyncio.to_thread(tts.load)  # 首次约 10~30s
    print(f"[TTS 模型就绪 +{time.perf_counter() - t0:.2f}s]")

    joiner = SpeechJoiner(tts)
    first_token_at: float | None = None

    async def tokens_with_log() -> AsyncIterator[str]:
        nonlocal first_token_at
        async for token in orch.stream_reply(text):
            if first_token_at is None:
                first_token_at = time.perf_counter()
                print(f"[LLM 首 token +{first_token_at - t0:.2f}s]")
            print(token, end="", flush=True)
            yield token
        print()

    chunks: list[bytes] = []
    async for frame in joiner.run(tokens_with_log()):
        chunks.append(frame.data)
    total = time.perf_counter() - t0
    data = b"".join(chunks)
    with wave.open("recordings/joiner_demo.wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(data)
    print(
        f"总耗时 {total:.1f}s | 音频 {len(data) / 2 / 24000:.1f}s "
        f"→ recordings/joiner_demo.wav"
    )


if __name__ == "__main__":
    asyncio.run(main())
