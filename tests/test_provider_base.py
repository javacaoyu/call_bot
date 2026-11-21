"""Provider 统一地基单元测试（工厂分发与配置结构，无模型加载）。"""

import pytest

from callbot.providers.asr import FunASRStreamingASR
from callbot.providers.base import (
    ProviderConfig,
    create_asr,
    create_llm,
    create_tts,
)
from callbot.providers.llm import DeepSeekStreamingLLM
from callbot.providers.tts import CosyVoice2StreamingTTS


def test_provider_config_defaults() -> None:
    """配置结构：kind 必填，其余字段默认为空。"""
    cfg = ProviderConfig(kind="funasr")
    assert cfg.base_url == ""
    assert cfg.api_key == ""
    assert cfg.model == ""
    assert cfg.params == {}


def test_create_asr_funasr() -> None:
    """funasr kind 返回本地实现（惰性，不加载模型）。"""
    asr = create_asr(ProviderConfig(kind="funasr"))
    assert isinstance(asr, FunASRStreamingASR)


def test_create_asr_unknown_kind() -> None:
    """未知 kind 报错。"""
    with pytest.raises(ValueError, match="未知 ASR provider"):
        create_asr(ProviderConfig(kind="nope"))


def test_create_asr_params_model_dir() -> None:
    """params.model_dir 透传本地模型路径。"""
    asr = create_asr(ProviderConfig(kind="funasr", params={"model_dir": "/x"}))
    assert isinstance(asr, FunASRStreamingASR)
    assert asr._model_dir == "/x"  # noqa: SLF001


def test_create_tts_cosyvoice() -> None:
    """cosyvoice kind 返回本地实现（惰性，不加载模型）。"""
    tts = create_tts(ProviderConfig(kind="cosyvoice"))
    assert isinstance(tts, CosyVoice2StreamingTTS)


def test_create_tts_unknown_kind() -> None:
    """未知 kind 报错。"""
    with pytest.raises(ValueError, match="未知 TTS provider"):
        create_tts(ProviderConfig(kind="nope"))


def test_create_llm_passthrough() -> None:
    """LLM 工厂：端点三件套透传（OpenAI 兼容统一，无 kind 分发）。"""
    llm = create_llm(
        ProviderConfig(kind="deepseek", base_url="http://x", api_key="k", model="m")
    )
    assert isinstance(llm, DeepSeekStreamingLLM)
    assert llm._model == "m"  # noqa: SLF001
    assert str(llm._client.base_url) == "http://x"  # noqa: SLF001 - AsyncOpenAI 归一化
