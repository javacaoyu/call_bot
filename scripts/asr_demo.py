"""ASR 流式转写演示：wav 文件 → ConversationEngine → 控制台转写。

用法：uv run python scripts/asr_demo.py <wav路径>
"""

import sys

import torch
import torchaudio

from callbot.engine.engine import ConversationEngine
from callbot.engine.frames import AudioFrame
from callbot.providers.asr import ASRResult, FunASRStreamingASR

CHUNK_MS = 20


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: uv run python scripts/asr_demo.py <wav路径>")
        sys.exit(1)
    wav, sr = torchaudio.load(sys.argv[1])
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)
    wav = wav.mean(dim=0)  # 单声道
    pcm = (wav.clamp(-1, 1) * 32767).to(dtype=torch.int16).numpy()

    asr = FunASRStreamingASR()
    asr.load()

    # 模型输出约定：每个 chunk 吐增量文本，拼接全部增量即完整转写；
    # is_final 块若只含尾部静音，增量可能为空（属正常现象）
    all_texts: list[str] = []

    def on_transcript(result: ASRResult) -> None:
        all_texts.append(result.text)
        print(("【final】" if result.is_final else "【partial】") + result.text)

    engine = ConversationEngine()
    engine.attach_asr(asr, on_transcript)
    engine.start()

    samples_per_chunk = int(16000 * CHUNK_MS / 1000)
    for i in range(0, len(pcm), samples_per_chunk):
        frame = AudioFrame(data=pcm[i : i + samples_per_chunk].tobytes())
        engine.feed_audio(frame)
    engine.flush_asr()
    engine.stop()
    print("完整转写:", "".join(all_texts))


if __name__ == "__main__":
    main()
