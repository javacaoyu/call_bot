"""TTS Provider 单元测试（转换纯函数；真实模型靠冒烟验证）。"""

import numpy as np
import torch

from callbot.providers.tts import tensor_to_audio_frame


def test_tensor_to_audio_frame() -> None:
    """[-1,1] float 张量转 PCM16，采样率透传。"""
    samples = torch.tensor([[0.0, 1.0, -1.0, 0.5]])
    frame = tensor_to_audio_frame(samples, 24000)
    assert frame.sample_rate == 24000
    pcm = np.frombuffer(frame.data, dtype=np.int16)
    assert pcm[0] == 0
    assert pcm[1] == 32767
    assert pcm[2] == -32767
    assert abs(int(pcm[3]) - 16383) <= 1  # 0.5 * 32767 截断


def test_tensor_to_audio_frame_clamps() -> None:
    """越界值截断到 int16 范围。"""
    samples = torch.tensor([[2.0, -2.0]])
    pcm = np.frombuffer(tensor_to_audio_frame(samples, 16000).data, dtype=np.int16)
    assert [int(x) for x in pcm] == [32767, -32767]


async def test_synthesize_empty_text_skipped() -> None:
    """空/纯空白文本直接返回，不加载模型不产出帧。"""
    from callbot.providers.tts import CosyVoice2StreamingTTS

    tts = CosyVoice2StreamingTTS()  # 未加载模型
    frames = [f async for f in tts.synthesize("  \n ")]
    assert frames == []
