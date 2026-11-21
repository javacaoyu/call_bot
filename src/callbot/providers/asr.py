"""ASR Provider：流式转写接口与 FunASR 本地实现。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import torch

from callbot.engine.frames import AudioFrame

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ASRResult:
    """一次流式转写结果。

    text: 增量文本（进 utterance 累积）；is_final: 是否最终结果。
    snapshot: 页面完整快照（句级修订式 ASR 如千问使用，前端替换显示；
    增量式实现为 None，前端按增量追加）。
    """

    text: str
    is_final: bool
    snapshot: str | None = None


class StreamingASR(Protocol):
    """流式 ASR Provider 接口（本地 / 云端实现均遵循）。"""

    def load(self) -> None:
        """加载模型/初始化连接（懒加载、幂等；耗时操作放线程）。"""
        ...

    def set_callback(
        self, callback: Callable[[ASRResult], None] | None
    ) -> None:
        """注册增量转写回调（云端实现结果异步到达时直推；本地实现可空实现）。"""
        ...

    def process_chunk(self, frame: AudioFrame, is_final: bool = False) -> ASRResult | None:
        """送入一块 16k PCM16 音频，返回本次转写（无新文本时返回 None）。"""
        ...

    def reset(self) -> None:
        """清空流式缓存（新一轮会话）。"""
        ...


class FunASRStreamingASR:
    """FunASR paraformer 在线流式转写（本地 GPU）。

    分块参数沿用 WBS 1.3 实测配置：chunk_size [0,10,5] + 前视回看 4/1。

    输出约定（实测）：每个 chunk 返回「增量文本」，拼接全部增量即完整转写；
    is_final=True 仅标记收尾，若尾部为静音该块增量可为空（正常现象）。
    """

    def __init__(self, model_dir: str = "models/paraformer-zh-streaming") -> None:
        self._model_dir = model_dir
        self._model: Any = None
        self._cache: dict[str, Any] = {}

    def load(self) -> None:
        """加载模型（GPU 推理，首次约 10~20s，幂等）。"""
        if self._model is not None:
            return
        from funasr import AutoModel  # 延迟导入，避免无模型环境 import 即失败

        logger.info("加载 FunASR 模型 %s", self._model_dir)
        self._model = AutoModel(model=self._model_dir, disable_update=True)

    def set_callback(
        self, callback: Callable[[ASRResult], None] | None
    ) -> None:
        """本地实现结果同步返回，无需回调（满足 Protocol 的空实现）。"""

    def process_chunk(self, frame: AudioFrame, is_final: bool = False) -> ASRResult | None:
        """送入一块音频，返回本次转写结果（无新文本时 None）。"""
        if self._model is None:
            raise RuntimeError("ASR 模型未加载，请先调用 load()")
        samples = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32)
        tensor = torch.from_numpy(samples).unsqueeze(0)
        res = self._model.generate(
            input=tensor,
            cache=self._cache,
            is_final=is_final,
            chunk_size=[0, 10, 5],
            encoder_chunk_look_back=4,
            decoder_chunk_look_back=1,
        )
        if not res or not res[0].get("text"):
            return None
        return ASRResult(text=res[0]["text"], is_final=is_final)

    def reset(self) -> None:
        """清空流式缓存。"""
        self._cache = {}
