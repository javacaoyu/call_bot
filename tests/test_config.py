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
