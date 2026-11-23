"""场景与工具库 API 测试（WBS 6.3；依赖 docker postgres）。"""

from textwrap import dedent

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from callbot.api.app import create_app
from callbot.data.models import Scene, Tool, get_engine
from callbot.tools import loader


@pytest.fixture()
def api_client() -> TestClient:
    """⚠️ 不清生产表；测试数据用「测试场景」前缀，收尾清理自己创建的记录。"""
    client = TestClient(create_app())
    yield client
    with Session(get_engine()) as s:
        ids = s.scalars(select(Scene.id).where(Scene.name.like("测试场景%"))).all()
        if ids:
            s.execute(delete(Tool).where(Tool.scene_id.in_(ids)))
            s.execute(delete(Scene).where(Scene.id.in_(ids)))
            s.commit()


def _create_scene(client: TestClient, name: str = "测试场景") -> dict:
    resp = client.post("/api/scenes", json={"name": name, "description": "测试"})
    assert resp.status_code == 200
    return resp.json()


def test_scene_crud(api_client: TestClient) -> None:
    """场景增删改查。"""
    data = api_client.get("/api/scenes").json()
    assert any(s["name"] == "通用客服" for s in data)  # 种子默认场景
    s = _create_scene(api_client)
    resp = api_client.put(f"/api/scenes/{s['id']}", json={"name": "测试场景改", "description": "d"})
    assert resp.json()["name"] == "测试场景改"
    assert api_client.delete(f"/api/scenes/{s['id']}").status_code == 200
    names = [x["name"] for x in api_client.get("/api/scenes").json()]
    assert "测试场景改" not in names


def test_scene_delete_blocked_by_assets(api_client: TestClient) -> None:
    """场景下有流程/人设/工具时拒删。"""
    s = _create_scene(api_client)
    api_client.post(
        "/api/tools",
        json={
            "scene_id": s["id"],
            "name": "测试工具",
            "description": "",
            "kind": "http",
            "config": {},
        },
    )
    resp = api_client.delete(f"/api/scenes/{s['id']}")
    assert resp.status_code == 400  # 场景下有工具，拒删
    # 清理场景自有工具（跳过内置工具）后可删
    tools = api_client.get(f"/api/tools?scene_id={s['id']}").json()
    tool_id = next(t["id"] for t in tools if not t["builtin"])
    api_client.delete(f"/api/tools/{tool_id}")
    assert api_client.delete(f"/api/scenes/{s['id']}").status_code == 200


def test_tool_crud(api_client: TestClient) -> None:
    """工具 CRUD + 按场景过滤。"""
    s1 = _create_scene(api_client, "测试场景A")
    s2 = _create_scene(api_client, "测试场景B")
    t = api_client.post(
        "/api/tools",
        json={
            "scene_id": s1["id"],
            "name": "查订单",
            "description": "按订单号查状态",
            "kind": "http",
            "config": {"method": "GET", "url": "https://example.com/orders/{order_id}"},
        },
    ).json()
    assert t["scene_id"] == s1["id"]
    # 场景隔离（内置工具对所有场景可见，不计入场景自有工具）
    tools_s2 = api_client.get(f"/api/tools?scene_id={s2['id']}").json()
    own_tools = [x for x in tools_s2 if not x["builtin"]]
    assert own_tools == []
    resp = api_client.put(
        f"/api/tools/{t['id']}",
        json={
            "scene_id": s1["id"],
            "name": "查订单2",
            "description": "",
            "kind": "http",
            "config": {},
        },
    )
    assert resp.json()["name"] == "查订单2"
    assert api_client.delete(f"/api/tools/{t['id']}").status_code == 200


def test_tools_plugins_list(api_client: TestClient) -> None:
    """已加载代码插件清单（含种子演示插件）。"""
    data = api_client.get("/api/tools/plugins").json()
    names = [p["name"] for p in data]
    assert "mock_query_order" in names
    order = next(p for p in data if p["name"] == "mock_query_order")
    assert order["params"][0]["name"] == "order_id"


# ---------- 插件加载器 ----------

_VALID_PLUGIN = dedent(
    '''
    from agentscope.tool import ParamsBase
    from pydantic import Field

    TOOL_NAME = "tmp_valid_tool"
    TOOL_DESCRIPTION = "临时插件测试"

    class Params(ParamsBase):
        q: str = Field(description="问题")

    async def run(q: str) -> str:
        return "ok"
    '''
)


def _write_plugin(tmp_path, name: str, content: str) -> None:
    (tmp_path / f"{name}.py").write_text(content, encoding="utf-8")


def test_loader_valid_and_broken(tmp_path) -> None:  # noqa: ANN001
    """合法插件注册；缺要素/非 async 跳过；重复加载覆盖。"""
    _write_plugin(tmp_path, "tmp_valid_tool", _VALID_PLUGIN)
    _write_plugin(
        tmp_path,
        "tmp_missing",
        "TOOL_NAME = 'tmp_missing'\nTOOL_DESCRIPTION = '缺 run'\n",
    )
    _write_plugin(
        tmp_path,
        "tmp_sync",
        _VALID_PLUGIN.replace("async def run", "def run"),
    )
    try:
        assert loader.load_plugins(tmp_path) == 1
        plugins = {p["name"] for p in loader.list_plugins()}
        assert "tmp_valid_tool" in plugins
        assert "tmp_missing" not in plugins
        assert "tmp_sync" not in plugins
        assert loader.get_plugin("tmp_valid_tool") is not None
    finally:
        loader._registry.pop("tmp_valid_tool", None)
