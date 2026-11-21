"""Provider 统一地基（WBS 4.1）：配置结构、load 约定与工厂。

三环节切换的抽象层：ASR/TTS 按 kind 分发（本地开源 / 云端 API 不同实现）；
LLM 无 kind 分发——PRD 明确「统一 OpenAI 兼容，切换即换
base_url + api_key + model」（vLLM/Ollama/DeepSeek 同接口）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from callbot.providers.asr import StreamingASR
from callbot.providers.llm import DeepSeekStreamingLLM, StreamingLLM
from callbot.providers.tts import StreamingTTS


@dataclass
class ProviderConfig:
    """单环节 Provider 配置（4.3 配置驱动切换、4.4 Web 面板的数据结构）。

    kind: 实现标识（ASR: "funasr"；TTS: "cosyvoice"；云端 kind 4.2 接入）。
    base_url / api_key / model: OpenAI 兼容端点三件套（云端 LLM/ASR/TTS 通用）。
    params: 实现特有参数（本地模型路径、音色、方言等）。
    """

    kind: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    params: dict[str, Any] = field(default_factory=dict)


class ModelProvider(Protocol):
    """需要模型加载/连接初始化的 Provider 通用约定（本地 ASR/TTS 实现遵循）。"""

    def load(self) -> None:
        """加载模型（懒加载、幂等；耗时操作，调用方负责放线程执行）。"""
        ...


def create_asr(cfg: ProviderConfig) -> StreamingASR:
    """ASR 工厂：按 kind 分发（4.2 云端实现接入时扩充分支）。"""
    if cfg.kind == "funasr":
        from callbot.providers.asr import FunASRStreamingASR

        return FunASRStreamingASR(
            model_dir=cfg.params.get("model_dir", "models/paraformer-zh-streaming")
        )
    raise ValueError(f"未知 ASR provider: {cfg.kind}")


def create_tts(cfg: ProviderConfig) -> StreamingTTS:
    """TTS 工厂：按 kind 分发（4.2 云端实现接入时扩充分支）。"""
    if cfg.kind == "cosyvoice":
        from callbot.providers.tts import CosyVoice2StreamingTTS

        return CosyVoice2StreamingTTS()
    raise ValueError(f"未知 TTS provider: {cfg.kind}")


def create_llm(cfg: ProviderConfig) -> StreamingLLM:
    """LLM 工厂：OpenAI 兼容统一，无 kind 分发（切换即换端点三件套）。"""
    return DeepSeekStreamingLLM(base_url=cfg.base_url, api_key=cfg.api_key, model=cfg.model)
