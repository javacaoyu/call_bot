"""TTS 流式演示：一句话 → CosyVoice2 流式合成 → 存 recordings/tts_demo.wav。

用法：uv run python scripts/tts_demo.py [文本]
前置：LD_LIBRARY_PATH（见 CLAUDE.md）。
"""

import asyncio
import sys
import time
import wave

from callbot.providers.tts import CosyVoice2StreamingTTS


async def main() -> None:
    tts = CosyVoice2StreamingTTS()
    await asyncio.to_thread(tts.load)  # 首次约 10~30s
    text = sys.argv[1] if len(sys.argv) > 1 else "你好，这里是智能语音助手，请问有什么可以帮您？"
    print(f"合成: {text}")
    t0 = time.perf_counter()
    first_at: float | None = None
    chunks: list[bytes] = []
    async for frame in tts.synthesize(text):
        if first_at is None:
            first_at = time.perf_counter()
        chunks.append(frame.data)
        print(".", end="", flush=True)
    total = time.perf_counter() - t0
    data = b"".join(chunks)
    with wave.open("recordings/tts_demo.wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(data)
    print()
    print(
        f"首块 {first_at - t0:.2f}s | 总耗时 {total:.1f}s | "
        f"音频 {len(data) / 2 / 24000:.1f}s → recordings/tts_demo.wav"
    )


if __name__ == "__main__":
    asyncio.run(main())
