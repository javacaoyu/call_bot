"""音频帧模型（引擎媒体无关：只处理 PCM 帧）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioFrame:
    """一帧 PCM16 小端音频。

    约定：引擎内部统一 16kHz / 单声道；采样率不一致由 channel 层适配。
    """

    data: bytes
    sample_rate: int = 16000
    channels: int = 1


def frame_duration_ms(frame: AudioFrame) -> int:
    """帧时长（毫秒），按 PCM16 每样本 2 字节计算。"""
    samples = len(frame.data) // 2
    return round(samples / frame.sample_rate * 1000)
