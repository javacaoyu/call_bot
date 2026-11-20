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
