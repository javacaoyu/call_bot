"""Provider 统一地基单元测试（工厂分发与配置结构，无模型加载）。"""

import pytest

from callbot.config import Settings
from callbot.providers.asr import FunASRStreamingASR
from callbot.providers.base import (
    ProviderConfig,
    asr_config_from_settings,
    create_asr,
    create_llm,
    create_tts,
    tts_config_from_settings,
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


def _settings(**overrides: str) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_asr_config_funasr_default() -> None:
    """默认本地 kind：无密钥要求。"""
    cfg = asr_config_from_settings(_settings())
    assert cfg == ProviderConfig(kind="funasr")


def test_asr_config_qwen_mapping() -> None:
    """qwen：api_key 直接映射（无额外参数）。"""
    cfg = asr_config_from_settings(_settings(asr_kind="qwen", asr_qwen_api_key="k"))
    assert cfg.kind == "qwen"
    assert cfg.api_key == "k"


def test_asr_config_qwen_missing_key() -> None:
    """qwen 缺密钥报错并提示 env 名。"""
    with pytest.raises(ValueError, match="CALLBOT_ASR_QWEN_API_KEY"):
        asr_config_from_settings(_settings(asr_kind="qwen"))


def test_asr_config_volc_mapping() -> None:
    """volc：api_key + 默认 resource_id。"""
    cfg = asr_config_from_settings(_settings(asr_kind="volc", asr_volc_api_key="k"))
    assert cfg.kind == "volc"
    assert cfg.api_key == "k"
    assert cfg.params["resource_id"] == "volc.seedasr.sauc.duration"
    with pytest.raises(ValueError, match="CALLBOT_ASR_VOLC_API_KEY"):
        asr_config_from_settings(_settings(asr_kind="volc"))


def test_asr_config_unknown_kind() -> None:
    """未知 kind 报错。"""
    with pytest.raises(ValueError, match="未知 ASR provider"):
        asr_config_from_settings(_settings(asr_kind="nope"))


def test_tts_config_cosyvoice_default() -> None:
    """默认本地 kind：无密钥要求。"""
    cfg = tts_config_from_settings(_settings())
    assert cfg == ProviderConfig(kind="cosyvoice")



def test_tts_config_volc_mapping() -> None:
    """volc：api_key 复用 asr_volc_api_key，speaker 从 tts_volc_speaker 取。"""
    cfg = tts_config_from_settings(_settings(tts_kind="volc", asr_volc_api_key="k"))
    assert cfg.kind == "volc"
    assert cfg.api_key == "k"
    assert cfg.params["speaker"] == "zh_female_vv_uranus_bigtts"
    with pytest.raises(ValueError, match="CALLBOT_ASR_VOLC_API_KEY"):
        tts_config_from_settings(_settings(tts_kind="volc"))


def test_tts_config_qwen_mapping() -> None:
    """qwen：api_key 复用 asr_qwen_api_key，voice 从 tts_qwen_voice 取（同 Key 模式）。"""
    cfg = tts_config_from_settings(_settings(tts_kind="qwen", asr_qwen_api_key="k"))
    assert cfg.kind == "qwen"
    assert cfg.api_key == "k"
    assert cfg.params["voice"] == "longanhuan_v3.1"
    with pytest.raises(ValueError, match="CALLBOT_ASR_QWEN_API_KEY"):
        tts_config_from_settings(_settings(tts_kind="qwen"))


def test_tts_config_unknown_kind() -> None:
    """未知 kind 报错。"""
    with pytest.raises(ValueError, match="未知 TTS provider"):
        tts_config_from_settings(_settings(tts_kind="nope"))
