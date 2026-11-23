"""工具装配单元测试（WBS 6.3；依赖 docker postgres 与已加载插件）。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from callbot.api.app import create_app
from callbot.data.models import Scene, Tool, get_engine
from callbot.tools.executors import build_toolkit
from callbot.tools.loader import get_plugin


@pytest.fixture()
def api_client() -> TestClient:
    client = TestClient(create_app())
    yield client
    with Session(get_engine()) as s:
        ids = s.scalars(select(Scene.id).where(Scene.name.like("测试场景%"))).all()
        if ids:
            s.execute(delete(Tool).where(Tool.scene_id.in_(ids)))
            s.execute(delete(Scene).where(Scene.id.in_(ids)))
            s.commit()


def _scene_and_tool(client: TestClient, kind: str, config: dict) -> tuple[str, dict]:
    scene = client.post(
        "/api/scenes", json={"name": "测试场景工具", "description": ""}
    ).json()
    tool = client.post(
        "/api/tools",
        json={
            "scene_id": scene["id"],
            "name": f"测试工具{kind}",
            "description": "查订单",
            "kind": kind,
            "config": config,
        },
    ).json()
    return scene["id"], tool


async def test_build_toolkit_plugin(api_client: TestClient) -> None:
    """插件工具装配：注册表插件 → Toolkit 注册 + kwargs 调用。"""
    plugin = get_plugin("mock_query_order")
    assert plugin is not None  # 启动时已加载演示插件
    _, tool = _scene_and_tool(api_client, "plugin", {"plugin": "mock_query_order"})
    toolkit = await build_toolkit([tool["id"]])
    assert toolkit is not None
    registered = await toolkit.get_tool("测试工具plugin")
    assert registered is not None
    # **kwargs 调用语义端到端验证（AgentScope 2.0.12）
    resp = await registered.call(**{"order_id": "20261123001"})
    text = str(resp.content[0])
    assert "已发货" in text


async def test_build_toolkit_http(api_client: TestClient) -> None:
    """HTTP 工具装配：动态 schema 生成 + 注册。"""
    _, tool = _scene_and_tool(
        api_client,
        "http",
        {
            "method": "GET",
            "url": "https://example.com/orders/{order_id}",
            "params": [
                {"name": "order_id", "type": "string", "required": True, "description": "订单号"}
            ],
        },
    )
    toolkit = await build_toolkit([tool["id"]])
    assert toolkit is not None
    registered = await toolkit.get_tool("测试工具http")
    assert registered is not None
    assert "order_id" in registered.input_schema["properties"]


async def test_build_toolkit_missing_ids() -> None:
    """全部缺失/非法 → None（不装配）。"""
    assert await build_toolkit(["no-such-id"]) is None
    assert await build_toolkit([]) is None
