"""Silero VAD 模块（WBS 3.1）：PCM16 帧流 → 语音起音/端点事件。"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path

import numpy as np
import torch

from callbot.engine.frames import AudioFrame

logger = logging.getLogger(__name__)

# Silero VAD v5 @16k 固定块长：512 样本 = 32ms（实测 1024 样本会直接报错）
_BLOCK_SAMPLES = 512
_BLOCK_MS = 32
# 项目根（相对模型路径基于项目根解析，避免 cwd 漂移）：vad.py→engine→callbot→src→根
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class VADEvent(StrEnum):
    """VAD 事件：起音 / 端点（3.3 打断将复用 SPEECH_START 作为抢话信号）。"""

    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"


class SileroVAD:
    """Silero VAD 封装：任意长度 PCM16 帧 → 起音/端点事件。

    内部链路：帧缓冲累积 → 512 样本块（32ms@16k）→ jit 模型逐块推理 →
    平滑状态机（最小语音时长过滤杂音；静音容忍判定端点）。

    事件语义（边缘触发，状态迁移时各发一次）：
    - SPEECH_START：静音中连续语音达到 min_speech_ms；
    - SPEECH_END：语音中连续静音达到 min_silence_ms。
    """

    def __init__(
        self,
        model_path: str = "models/silero_vad.jit",
        threshold: float = 0.5,
        min_speech_ms: int = 250,
        min_silence_ms: int = 400,
    ) -> None:
        self._model_path = _PROJECT_ROOT / model_path
        self._threshold = threshold
        self._min_speech_ms = min_speech_ms
        self._min_silence_ms = min_silence_ms
        self._model: torch.jit.ScriptModule | None = None
        self._buffer = bytearray()
        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0

    @property
    def in_speech(self) -> bool:
        """当前是否处于语音段中。"""
        return self._in_speech

    def load(self) -> None:
        """加载 jit 模型（线程安全由调用方负责，如 asyncio.to_thread）。"""
        if self._model is not None:
            return
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"VAD 模型不存在: {self._model_path}，请从 "
                "https://github.com/snakers4/silero-vad/raw/master/"
                "src/silero_vad/data/silero_vad.jit 下载"
            )
        self._model = torch.jit.load(str(self._model_path))
        self._model.eval()
        logger.info("Silero VAD 模型已加载: %s", self._model_path)

    def _consume_block(self, block: bytes) -> VADEvent | None:
        """推理一个 512 样本块并推进状态机，返回本次迁移产生的事件。"""
        assert self._model is not None
        samples = torch.tensor(np.frombuffer(block, dtype=np.int16)).float() / 32768.0
        prob = float(self._model(samples, 16000).item())
        event: VADEvent | None = None
        if not self._in_speech:
            if prob >= self._threshold:
                self._speech_ms += _BLOCK_MS
                if self._speech_ms >= self._min_speech_ms:
                    self._in_speech = True
                    self._silence_ms = 0.0
                    event = VADEvent.SPEECH_START
                    logger.debug("VAD 起音（%dms 语音）", self._speech_ms)
            else:
                self._speech_ms = 0.0
        else:
            if prob < self._threshold:
                self._silence_ms += _BLOCK_MS
                if self._silence_ms >= self._min_silence_ms:
                    self._in_speech = False
                    self._speech_ms = 0.0
                    event = VADEvent.SPEECH_END
                    logger.debug("VAD 端点（%dms 静音）", self._silence_ms)
            else:
                self._silence_ms = 0.0
        return event

    def process_frame(self, frame: AudioFrame) -> VADEvent | None:
        """处理一帧任意长度 PCM16 音频，返回事件（无迁移返回 None）。

        帧长不足 512 样本时先入缓冲，累积满后逐块处理。
        """
        if self._model is None:
            return None
        self._buffer.extend(frame.data)
        event: VADEvent | None = None
        while len(self._buffer) >= _BLOCK_SAMPLES * 2:
            block = bytes(self._buffer[:_BLOCK_SAMPLES * 2])
            del self._buffer[:_BLOCK_SAMPLES * 2]
            result = self._consume_block(block)
            if result is not None:
                event = result
        return event

    def flush(self) -> VADEvent | None:
        """收尾：若仍在语音段中，强制判定端点（供会话结束/打断链路调用）。"""
        self._buffer.clear()
        if self._in_speech:
            self._in_speech = False
            self._speech_ms = 0.0
            self._silence_ms = 0.0
            return VADEvent.SPEECH_END
        return None

    def reset(self) -> None:
        """重置状态与缓冲（新轮对话）。"""
        self._buffer.clear()
        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
