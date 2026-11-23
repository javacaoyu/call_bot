"""人设管理 API 测试（WBS 6.1；依赖 docker postgres）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from callbot.api.app import create_app
from callbot.data.models import Persona, get_engine


@pytest.fixture()
def api_client() -> TestClient:
    # 清空人设表保证测试隔离（种子由 init_db 在 app 启动时补）
    with Session(get_engine()) as s:
        s.execute(delete(Persona))
        s.commit()
    return TestClient(create_app())


def _create(client: TestClient, name: str = "测试人设") -> dict:
    resp = client.post(
        "/api/personas",
        json={"name": name, "description": "测试", "system_prompt": "你是测试。"},
    )
    assert resp.status_code == 200
    return resp.json()


def test_list_seeded_default(api_client: TestClient) -> None:
    """启动种子：默认人设存在且激活。"""
    data = api_client.get("/api/personas").json()
    assert len(data) == 1
    assert data[0]["name"] == "默认客服"
    assert data[0]["is_active"] is True


def test_create_update_delete(api_client: TestClient) -> None:
    """CRUD 全流程。"""
    p = _create(api_client)
    assert p["is_active"] is False
    # 更新
    resp = api_client.put(
        f"/api/personas/{p['id']}",
        json={"name": "改名", "description": "d2", "system_prompt": "新 prompt。"},
    )
    assert resp.json()["name"] == "改名"
    # 删除
    assert api_client.delete(f"/api/personas/{p['id']}").status_code == 200
    names = [x["name"] for x in api_client.get("/api/personas").json()]
    assert "改名" not in names


def test_activate_exclusive(api_client: TestClient) -> None:
    """激活互斥：新激活后旧人设变非激活。"""
    p2 = _create(api_client, "人设二")
    resp = api_client.post(f"/api/personas/{p2['id']}/activate")
    assert resp.json()["is_active"] is True
    data = api_client.get("/api/personas").json()
    active = [x for x in data if x["is_active"]]
    assert len(active) == 1
    assert active[0]["id"] == p2["id"]


def test_cannot_delete_active(api_client: TestClient) -> None:
    """激活中的人设不可删除。"""
    active_id = next(x["id"] for x in api_client.get("/api/personas").json() if x["is_active"])
    resp = api_client.delete(f"/api/personas/{active_id}")
    assert resp.status_code == 400


def test_get_active_prompt() -> None:
    """get_active_persona_prompt 返回激活人设文本。"""
    from callbot.data.personas import get_active_persona_prompt

    prompt = get_active_persona_prompt()
    assert isinstance(prompt, str) and prompt


def test_invalid_ids(api_client: TestClient) -> None:
    """非法 ID 422；不存在 404。"""
    resp = api_client.put(
        "/api/personas/xyz",
        json={"name": "a", "description": "", "system_prompt": "b"},
    )
    assert resp.status_code == 422
    missing = str(uuid.uuid4())
    assert api_client.delete(f"/api/personas/{missing}").status_code == 404
    assert api_client.post(f"/api/personas/{missing}/activate").status_code == 404
