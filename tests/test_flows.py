"""话术流程图 API 与定义校验测试（WBS 6.3；依赖 docker postgres）。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from callbot.api.app import create_app
from callbot.data.models import Flow, FlowVersion, Scene, Tool, get_engine
from callbot.flow.definitions import build_default_flow, validate_flow_definition


@pytest.fixture()
def api_client() -> TestClient:
    """测试数据用「测试场景」前缀，收尾清理。"""
    client = TestClient(create_app())
    yield client
    with Session(get_engine()) as s:
        ids = s.scalars(select(Scene.id).where(Scene.name.like("测试场景%"))).all()
        if ids:
            s.execute(delete(FlowVersion).where(FlowVersion.flow_id.in_(select(Flow.id).where(Flow.scene_id.in_(ids)))))
            s.execute(delete(Tool).where(Tool.scene_id.in_(ids)))
            s.execute(delete(Flow).where(Flow.scene_id.in_(ids)))
            s.execute(delete(Scene).where(Scene.id.in_(ids)))
            s.commit()


def _scene(client: TestClient) -> dict:
    resp = client.post("/api/scenes", json={"name": "测试场景流程", "description": ""})
    assert resp.status_code == 200
    return resp.json()


def _flow(client: TestClient, scene_id: str) -> dict:
    resp = client.post(
        "/api/flows", json={"scene_id": scene_id, "name": "测试流程", "description": ""}
    )
    assert resp.status_code == 200
    return resp.json()


def test_flow_create_and_duplicate(api_client: TestClient) -> None:
    """新建流程 = 默认模板草稿；一场景一流程。"""
    s = _scene(api_client)
    f = _flow(api_client, s["id"])
    assert f["version"] == 0  # 未发布
    assert f["has_unpublished_changes"] is True
    detail = api_client.get(f"/api/flows/{f['id']}").json()
    assert validate_flow_definition(detail["draft"]) == []  # 默认模板合法
    # 同场景重复建 → 400
    resp = api_client.post(
        "/api/flows", json={"scene_id": s["id"], "name": "再来一个", "description": ""}
    )
    assert resp.status_code == 400


def test_flow_publish_rollback(api_client: TestClient) -> None:
    """发布版本递增 + 快照；回滚 = 历史快照重新发布。"""
    s = _scene(api_client)
    f = _flow(api_client, s["id"])
    v1 = api_client.post(f"/api/flows/{f['id']}/publish").json()
    assert v1["version"] == 1
    assert v1["has_unpublished_changes"] is False
    # 改草稿（结束语文本）→ 发布 v2
    draft = api_client.get(f"/api/flows/{f['id']}").json()["draft"]
    end_node = next(n for n in draft["nodes"] if n["type"] == "end")
    end_node["data"]["text"] = "再见2"
    api_client.put(f"/api/flows/{f['id']}", json={"draft": draft})
    v2 = api_client.post(f"/api/flows/{f['id']}/publish").json()
    assert v2["version"] == 2
    # 回滚到 v1 → 新版本 3，内容 = v1 定义（结束语恢复原文本）
    v3 = api_client.post(f"/api/flows/{f['id']}/rollback/1").json()
    assert v3["version"] == 3
    published = api_client.get(f"/api/flows/{f['id']}").json()["published"]
    end_published = next(n for n in published["nodes"] if n["type"] == "end")
    assert end_published["data"]["text"] == "感谢您的接听，再见。"


def test_flow_publish_rejects_invalid(api_client: TestClient) -> None:
    """非法图拒发（缺 opening）。"""
    s = _scene(api_client)
    f = _flow(api_client, s["id"])
    draft = build_default_flow()
    draft["nodes"] = [n for n in draft["nodes"] if n["type"] != "opening"]
    api_client.put(f"/api/flows/{f['id']}", json={"draft": draft})
    resp = api_client.post(f"/api/flows/{f['id']}/publish")
    assert resp.status_code == 400
    assert "opening" in resp.json()["detail"]


def test_flow_publish_tool_binding(api_client: TestClient) -> None:
    """handler 绑定工具必须属于本场景。"""
    s = _scene(api_client)
    f = _flow(api_client, s["id"])
    draft = build_default_flow()
    for n in draft["nodes"]:
        if n["type"] == "handler":
            n["data"]["tool_ids"] = ["no-such-tool"]
    api_client.put(f"/api/flows/{f['id']}", json={"draft": draft})
    resp = api_client.post(f"/api/flows/{f['id']}/publish")
    assert resp.status_code == 400
    assert "工具" in resp.json()["detail"]
    # 建工具绑定后发布通过
    tool = api_client.post(
        "/api/tools",
        json={
            "scene_id": s["id"],
            "name": "测试工具",
            "description": "",
            "kind": "http",
            "config": {},
        },
    ).json()
    for n in draft["nodes"]:
        if n["type"] == "handler":
            n["data"]["tool_ids"] = [tool["id"]]
    api_client.put(f"/api/flows/{f['id']}", json={"draft": draft})
    assert api_client.post(f"/api/flows/{f['id']}/publish").status_code == 200


# ---------- 校验函数 ----------


def test_validate_default_flow_ok() -> None:
    """默认流程模板合法。"""
    assert validate_flow_definition(build_default_flow()) == []


def test_validate_missing_opening() -> None:
    d = build_default_flow()
    d["nodes"] = [n for n in d["nodes"] if n["type"] != "opening"]
    assert any("opening" in e for e in validate_flow_definition(d))


def test_validate_duplicate_intent_name() -> None:
    d = build_default_flow()
    d["edges"].append(
        {
            "id": "e5",
            "from": "n_intent",
            "to": "n_main",
            "intent": {"name": "结束通话", "keywords": "", "description": "重复"},
        }
    )
    assert any("重复" in e for e in validate_flow_definition(d))


def test_validate_two_fallbacks() -> None:
    d = build_default_flow()
    d["edges"].append({"id": "e5", "from": "n_intent", "to": "n_main"})
    assert any("兜底" in e for e in validate_flow_definition(d))


def test_validate_handler_must_loop_back() -> None:
    d = build_default_flow()
    d["edges"] = [e for e in d["edges"] if not (e["from"] == "n_main")]
    assert any("回连" in e for e in validate_flow_definition(d))


def test_validate_unreachable_node() -> None:
    d = build_default_flow()
    d["nodes"].append({"id": "n_orphan", "type": "end", "data": {"text": "孤立"}})
    assert any("不可达" in e for e in validate_flow_definition(d))


def test_validate_bad_inputs() -> None:
    """非对象/缺节点/重复 id 等粗粒度非法输入。"""
    assert validate_flow_definition("not a dict") == ["定义必须是 JSON 对象"]
    assert validate_flow_definition({"nodes": []}) == ["必须包含节点列表"]
    d = build_default_flow()
    d["nodes"][0]["id"] = d["nodes"][1]["id"]
    assert any("重复" in e for e in validate_flow_definition(d))
