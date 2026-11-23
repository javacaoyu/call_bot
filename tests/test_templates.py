"""行业模板库测试（WBS 6.5；依赖 docker postgres）。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from callbot.api.app import create_app
from callbot.data.models import Flow, FlowVersion, Persona, Scene, get_engine
from callbot.flow.definitions import validate_flow_definition
from callbot.templates import TEMPLATES, get_template


def test_template_flow_definitions_valid() -> None:
    """全部模板的流程图定义通过结构校验（内容回归保障）。"""
    assert len(TEMPLATES) == 5
    for t in TEMPLATES:
        errors = validate_flow_definition(t["flow"])
        assert errors == [], f"模板 {t['key']} 定义非法: {errors}"


def test_template_keys_and_fields() -> None:
    """key 唯一且字段齐全。"""
    keys = [t["key"] for t in TEMPLATES]
    assert len(keys) == len(set(keys))
    industries = {t["industry"] for t in TEMPLATES}
    assert industries == {"营销", "催收", "回访", "通知", "客服"}
    for t in TEMPLATES:
        assert t["persona"]["system_prompt"]
        assert t["persona"]["opening"]
    assert get_template("collection")["name"] == "银行信用卡催收"
    assert get_template("no-such") is None


@pytest.fixture()
def api_client() -> TestClient:
    client = TestClient(create_app())
    yield client
    # 清理实例化产生的资产（按模板场景名前缀 + 精确 id 双保险）
    with Session(get_engine()) as s:
        template_scene_names = {t["name"] for t in TEMPLATES}
        ids = s.scalars(
            select(Scene.id).where(Scene.name.in_(template_scene_names))
        ).all()
        if ids:
            s.execute(delete(FlowVersion).where(FlowVersion.flow_id.in_(select(Flow.id).where(Flow.scene_id.in_(ids)))))
            s.execute(delete(Persona).where(Persona.scene_id.in_(ids)))
            s.execute(delete(Flow).where(Flow.scene_id.in_(ids)))
            s.execute(delete(Scene).where(Scene.id.in_(ids)))
            s.commit()


def test_list_templates(api_client: TestClient) -> None:
    """模板列表摘要字段。"""
    data = api_client.get("/api/templates").json()
    assert len(data) == 5
    first = data[0]
    assert {"key", "industry", "name", "description", "persona_name",
            "node_count", "handler_count", "intent_count"} <= set(first)
    collection = next(t for t in data if t["key"] == "collection")
    assert collection["handler_count"] == 5
    assert collection["intent_count"] == 5  # 含结束通话


def test_instantiate_template(api_client: TestClient) -> None:
    """实例化：场景 + 人设 + 流程（v1 已发布）；可重复实例化。"""
    r1 = api_client.post("/api/templates/collection/instantiate").json()
    assert r1["flow_version"] == 1
    scene1 = api_client.get("/api/scenes").json()
    names = [s["name"] for s in scene1]
    assert r1["scene_name"] in names
    # 流程已发布 + 草稿一致
    flow = api_client.get(f"/api/flows/{r1['flow_id']}").json()
    assert flow["version"] == 1
    assert flow["published"] == flow["draft"]
    # 人设挂在场景下
    persona = api_client.get(f"/api/personas?scene_id={r1['scene_id']}").json()
    assert len(persona) == 1
    assert persona[0]["name"] == "银行催收专员"
    # 重复实例化互不影响
    r2 = api_client.post("/api/templates/collection/instantiate").json()
    assert r2["scene_id"] != r1["scene_id"]


def test_instantiate_missing_template(api_client: TestClient) -> None:
    """不存在的模板 404。"""
    assert api_client.post("/api/templates/no-such/instantiate").status_code == 404
