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


def asr_config_from_settings(settings: Any) -> ProviderConfig:
    """Settings → ASR ProviderConfig（4.3 配置驱动切换）。

    云端 kind 缺失必填密钥时抛 ValueError（提示对应 env 名），
    启动即失败——比运行到一半才报错更易排查。
    密钥按平台独立：volc 用 asr_volc_api_key、qwen 用 asr_qwen_api_key。
    """
    if settings.asr_kind == "funasr":
        return ProviderConfig(kind="funasr")
    if settings.asr_kind == "volc":
        if not settings.asr_volc_api_key:
            raise ValueError("volc ASR 缺少配置: CALLBOT_ASR_VOLC_API_KEY")
        return ProviderConfig(
            kind="volc",
            api_key=settings.asr_volc_api_key,
            params={"resource_id": settings.asr_resource_id},
        )
    if settings.asr_kind == "qwen":
        if not settings.asr_qwen_api_key:
            raise ValueError("qwen ASR 缺少配置: CALLBOT_ASR_QWEN_API_KEY")
        return ProviderConfig(
            kind="qwen",
            api_key=settings.asr_qwen_api_key,
            params={"model": settings.asr_qwen_model},
        )
    raise ValueError(f"未知 ASR provider: {settings.asr_kind}")


def tts_config_from_settings(settings: Any) -> ProviderConfig:
    """Settings → TTS ProviderConfig（4.3 配置驱动切换）。

    密钥复用同平台 ASR Key（火山 X-Api-Key 跨服务通用；千问 DashScope Key 同）。
    """
    if settings.tts_kind == "cosyvoice":
        return ProviderConfig(kind="cosyvoice")
    if settings.tts_kind == "volc":
        if not settings.asr_volc_api_key:
            raise ValueError("volc TTS 缺少配置: CALLBOT_ASR_VOLC_API_KEY（火山 Key 通用）")
        return ProviderConfig(
            kind="volc",
            api_key=settings.asr_volc_api_key,
            params={"speaker": settings.tts_volc_speaker},
        )
    if settings.tts_kind == "qwen":
        if not settings.asr_qwen_api_key:
            raise ValueError("qwen TTS 缺少配置: CALLBOT_ASR_QWEN_API_KEY（千问 Key 通用）")
        return ProviderConfig(
            kind="qwen",
            api_key=settings.asr_qwen_api_key,
            params={"voice": settings.tts_qwen_voice},
        )
    raise ValueError(f"未知 TTS provider: {settings.tts_kind}")


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
    """ASR 工厂：按 kind 分发（funasr 本地；volc/qwen 云端）。"""
    if cfg.kind == "funasr":
        from callbot.providers.asr import FunASRStreamingASR

        return FunASRStreamingASR(
            model_dir=cfg.params.get("model_dir", "models/paraformer-zh-streaming")
        )
    if cfg.kind == "volc":
        from callbot.providers.cloud.volc_asr import VolcStreamingASR

        return VolcStreamingASR(
            api_key=cfg.api_key,
            resource_id=cfg.params.get("resource_id", "volc.seedasr.sauc.duration"),
        )
    if cfg.kind == "qwen":
        from callbot.providers.cloud.qwen_asr import QwenStreamingASR

        return QwenStreamingASR(
            api_key=cfg.api_key,
            model=cfg.params.get("model", "qwen-audio-3.1-asr-flash-streaming"),
        )
    raise ValueError(f"未知 ASR provider: {cfg.kind}")


def create_tts(cfg: ProviderConfig) -> StreamingTTS:
    """TTS 工厂：按 kind 分发（cosyvoice 本地；volc/qwen 云端）。"""
    if cfg.kind == "cosyvoice":
        from callbot.providers.tts import CosyVoice2StreamingTTS

        return CosyVoice2StreamingTTS()
    if cfg.kind == "volc":
        from callbot.providers.cloud.volc_tts import VolcStreamingTTS

        return VolcStreamingTTS(
            api_key=cfg.api_key,
            speaker=cfg.params.get(
                "speaker", "zh_female_vv_uranus_bigtts"
            ),
        )
    if cfg.kind == "qwen":
        from callbot.providers.cloud.qwen_tts import QwenStreamingTTS

        return QwenStreamingTTS(
            api_key=cfg.api_key,
            voice=cfg.params.get("voice", "longanhuan_v3.1"),
        )
    raise ValueError(f"未知 TTS provider: {cfg.kind}")


def create_llm(cfg: ProviderConfig) -> StreamingLLM:
    """LLM 工厂：OpenAI 兼容统一，无 kind 分发（切换即换端点三件套）。"""
    return DeepSeekStreamingLLM(base_url=cfg.base_url, api_key=cfg.api_key, model=cfg.model)
