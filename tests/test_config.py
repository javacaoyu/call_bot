"""Settings 配置单元测试。"""

import pytest

from callbot.config import Settings


def test_settings_defaults() -> None:
    """默认值应正确且不受 .env 影响。"""
    settings = Settings(_env_file=None)
    assert settings.app_name == "callbot"
    assert settings.env == "dev"
    assert settings.log_level == "INFO"


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CALLBOT_ 前缀环境变量应覆盖默认值。"""
    monkeypatch.setenv("CALLBOT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CALLBOT_ENV", "test")
    settings = Settings(_env_file=None)
    assert settings.log_level == "DEBUG"
    assert settings.env == "test"


def test_settings_vad_defaults() -> None:
    """VAD 灵敏度参数默认值与 env 覆盖（3.4 打断调优旋钮）。"""
    settings = Settings(_env_file=None)
    assert settings.vad_threshold == 0.5
    assert settings.vad_min_speech_ms == 250
    assert settings.vad_min_silence_ms == 400


def test_settings_vad_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CALLBOT_VAD_ 前缀环境变量应覆盖 VAD 参数。"""
    monkeypatch.setenv("CALLBOT_VAD_MIN_SPEECH_MS", "120")
    monkeypatch.setenv("CALLBOT_VAD_MIN_SILENCE_MS", "300")
    settings = Settings(_env_file=None)
    assert settings.vad_min_speech_ms == 120
    assert settings.vad_min_silence_ms == 300


def test_settings_provider_kinds() -> None:
    """三环节 kind 默认值与环境覆盖（4.1 工厂配置入口）。"""
    settings = Settings(_env_file=None)
    assert settings.asr_kind == "funasr"
    assert settings.tts_kind == "cosyvoice"


def test_settings_provider_kind_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CALLBOT_ASR_KIND / CALLBOT_TTS_KIND 环境变量覆盖。"""
    monkeypatch.setenv("CALLBOT_ASR_KIND", "qwen")
    monkeypatch.setenv("CALLBOT_TTS_KIND", "qwen")
    settings = Settings(_env_file=None)
    assert settings.asr_kind == "qwen"
    assert settings.tts_kind == "qwen"


def test_settings_cloud_provider_defaults() -> None:
    """云端密钥字段默认值（4.3 配置驱动切换）。"""
    settings = Settings(_env_file=None)
    assert settings.asr_volc_api_key == ""
    assert settings.asr_qwen_api_key == ""
    assert settings.asr_resource_id == "volc.seedasr.sauc.duration"
    assert settings.asr_qwen_model == "qwen-audio-3.1-asr-flash-streaming"
    assert settings.tts_volc_speaker == "zh_female_vv_uranus_bigtts"
    assert settings.tts_qwen_voice == "longanhuan_v3.1"


def test_settings_cloud_provider_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CALLBOT_ASR_/CALLBOT_TTS_ 前缀环境变量覆盖云端密钥。"""
    monkeypatch.setenv("CALLBOT_ASR_VOLC_API_KEY", "key1")
    monkeypatch.setenv("CALLBOT_TTS_QWEN_VOICE", "voice1")
    settings = Settings(_env_file=None)
    assert settings.asr_volc_api_key == "key1"
    assert settings.tts_qwen_voice == "voice1"
