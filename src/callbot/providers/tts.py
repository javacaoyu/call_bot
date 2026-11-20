"""TTS Provider：流式合成接口与 CosyVoice2 本地实现。"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

import torch

from callbot.engine.frames import AudioFrame

logger = logging.getLogger(__name__)

_COSYVOICE_SAMPLE_RATE = 24000

# CosyVoice2 依赖源码路径（CLAUDE.md：matcha 与 CosyVoice 以源码方式使用，不入库）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_COSYVOICE_DIR = _PROJECT_ROOT / "third_party" / "CosyVoice"
_MATCHA_DIR = _PROJECT_ROOT / "third_party" / "Matcha-TTS"


class StreamingTTS(Protocol):
    """流式 TTS Provider 接口（本地 / 云端实现均遵循）。"""

    def synthesize(
        self,
        text: str,
        instruct_text: str = "",
        prompt_wav: str = "",
        speed: float = 1.0,
    ) -> AsyncIterator[AudioFrame]:
        """流式合成文本，逐块产出 AudioFrame。"""
        ...


_SENTINEL = object()


def _next_chunk(generator: Any) -> Any:
    """线程安全取下一块：StopIteration 转为哨兵（不可穿过 Future 再抛出）。"""
    try:
        return next(generator)
    except StopIteration:
        return _SENTINEL


def tensor_to_audio_frame(samples: torch.Tensor, sample_rate: int) -> AudioFrame:
    """float32 [-1, 1] 波形张量（1, N）→ PCM16 AudioFrame（越界自动截断）。"""
    pcm = (samples.clamp(-1.0, 1.0) * 32767.0).to(torch.int16).numpy()
    return AudioFrame(data=pcm.tobytes(), sample_rate=sample_rate)


class CosyVoice2StreamingTTS:
    """CosyVoice2-0.5B 流式 TTS（本地 GPU）。

    运行前置（见 CLAUDE.md「依赖与运行约束」）：
    - LD_LIBRARY_PATH 指向 venv 内 nvidia pip 库（否则 flow 落 CPU 产出坏音频）；
    - third_party/CosyVoice 与 third_party/Matcha-TTS 源码已就位。
    """

    def __init__(
        self,
        model_dir: str | None = None,
        default_prompt_wav: str | None = None,
        fp16: bool = True,
    ) -> None:
        self._model_dir = model_dir or str(
            _COSYVOICE_DIR / "pretrained_models" / "CosyVoice2-0.5B"
        )
        self._default_prompt_wav = default_prompt_wav or str(
            _COSYVOICE_DIR / "asset" / "zero_shot_prompt.wav"
        )
        self._fp16 = fp16
        self._model: Any = None

    def load(self) -> None:
        """加载模型（幂等，首次约 10~30s）。"""
        if self._model is not None:
            return
        for path in (str(_COSYVOICE_DIR), str(_MATCHA_DIR)):
            if path not in sys.path:
                sys.path.insert(0, path)
        from cosyvoice.cli.cosyvoice import CosyVoice2  # 延迟导入

        logger.info("加载 CosyVoice2 模型 %s", self._model_dir)
        self._model = CosyVoice2(
            self._model_dir,
            load_jit=False,
            load_trt=False,
            fp16=self._fp16,
        )

    async def synthesize(
        self,
        text: str,
        instruct_text: str = "",
        prompt_wav: str = "",
        speed: float = 1.0,
    ) -> AsyncIterator[AudioFrame]:
        """流式合成（instruct2 模式），逐块产出 24kHz PCM16 帧。"""
        if self._model is None:
            raise RuntimeError("TTS 模型未加载，请先调用 load()")
        prompt = prompt_wav or self._default_prompt_wav
        # instruct 必须以 <|endofprompt|> 结尾（缺失会导致 LLM 无限生成）
        instruct = (instruct_text or "用自然亲切的语气说话") + "<|endofprompt|>"
        gen = self._model.inference_instruct2(
            text,
            instruct,
            prompt,
            stream=True,
            speed=speed,
        )
        # 同步生成器 → 线程中逐块取，避免阻塞事件循环
        while True:
            output = await asyncio.to_thread(_next_chunk, gen)
            if output is _SENTINEL:
                break
            chunk = output["tts_speech"]
            yield tensor_to_audio_frame(chunk, _COSYVOICE_SAMPLE_RATE)
