"""Provider 配置存储与配置 API 单元测试（WBS 4.4）。"""

import json

import pytest
from fastapi.testclient import TestClient

from callbot.api.app import create_app
from callbot.channel import webrtc
from callbot.config import Settings
from callbot.providers import config_store


def test_load_missing_file(tmp_path) -> None:
    """文件不存在返回空覆盖。"""
    assert config_store.load_provider_overrides(tmp_path / "nope.json") == {}


def test_load_and_filter(tmp_path) -> None:
    """合法字段读入；非白名单字段被过滤。"""
    path = tmp_path / "pc.json"
    path.write_text(
        json.dumps({"asr_kind": "volc", "llm_model": "m1", "evil": "x"})
    )
    overrides = config_store.load_provider_overrides(path)
    assert overrides == {"asr_kind": "volc", "llm_model": "m1"}


def test_load_corrupt_file(tmp_path) -> None:
    """损坏 JSON 返回空覆盖（不阻断启动）。"""
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    assert config_store.load_provider_overrides(path) == {}


def test_save_roundtrip_and_filter(tmp_path) -> None:
    """保存只写白名单字段，读回一致。"""
    path = tmp_path / "pc.json"
    config_store.save_provider_overrides(
        {"tts_kind": "aliyun", "tts_token": "t", "unknown": "x"}, path
    )
    data = json.loads(path.read_text())
    assert data == {"tts_kind": "aliyun", "tts_token": "t"}
    assert config_store.load_provider_overrides(path) == data


def test_apply_overrides_to_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """覆盖层应用到 Settings 实例（json > env > 默认）。"""
    path = tmp_path / "pc.json"
    config_store.save_provider_overrides({"asr_kind": "qwen"}, path)
    monkeypatch.setattr(config_store, "_CONFIG_PATH", path)
    settings = Settings(_env_file=None)
    assert settings.asr_kind == "funasr"  # 默认
    config_store.apply_provider_overrides(settings)
    assert settings.asr_kind == "qwen"  # json 覆盖


def test_invalidate_shared_providers() -> None:
    """单例失效：非 None → None（热切换入口）。"""
    webrtc._SHARED_ASR = object()  # noqa: SLF001 - 测试注入
    webrtc._SHARED_TTS = object()  # noqa: SLF001
    webrtc.invalidate_shared_providers()
    assert webrtc._SHARED_ASR is None  # noqa: SLF001
    assert webrtc._SHARED_TTS is None  # noqa: SLF001


@pytest.fixture()
def api_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """隔离 provider_config.json 路径 + 隔离单例。"""
    monkeypatch.setattr(config_store, "_CONFIG_PATH", tmp_path / "pc.json")
    webrtc.invalidate_shared_providers()
    return TestClient(create_app())


def test_api_get_defaults(api_client: TestClient) -> None:
    """GET 返回当前生效配置（含默认 kind）。"""
    resp = api_client.get("/api/provider_config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["asr_kind"] == "funasr"
    assert data["tts_kind"] == "cosyvoice"


def test_api_put_and_reload(api_client: TestClient) -> None:
    """PUT 保存后 GET 读回新走线。"""
    resp = api_client.put("/api/provider_config", json={"asr_kind": "volc"})
    assert resp.status_code == 200
    assert resp.json()["asr_kind"] == "volc"
    assert api_client.get("/api/provider_config").json()["asr_kind"] == "volc"


def test_api_put_rejects_unknown_field(api_client: TestClient) -> None:
    """非法字段 422。"""
    resp = api_client.put("/api/provider_config", json={"hack": "x"})
    assert resp.status_code == 422


def test_api_put_rejects_non_string(api_client: TestClient) -> None:
    """非字符串值 422。"""
    resp = api_client.put("/api/provider_config", json={"asr_kind": 1})
    assert resp.status_code == 422
