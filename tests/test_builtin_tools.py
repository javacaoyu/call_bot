"""内置基础工具测试（7.1）：kb_search 所有场景默认存在、不可删除、模拟短答。"""


import pytest
from fastapi.testclient import TestClient

from callbot.api.app import create_app
from callbot.tools.executors import kb_search_run


@pytest.fixture()
def api_client() -> TestClient:
    return TestClient(create_app())


def test_builtin_kb_search_visible_in_every_scene(api_client: TestClient) -> None:
    """任何场景的工具列表都含 kb_search（builtin 标记）。"""
    scenes = api_client.get("/api/scenes").json()
    for scene in scenes:
        tools = api_client.get(f"/api/tools?scene_id={scene['id']}").json()
        builtin = [t for t in tools if t["builtin"]]
        assert len(builtin) == 1, f"场景 {scene['name']} 缺内置工具"
        assert builtin[0]["name"] == "kb_search"


def test_builtin_kb_search_undeletable(api_client: TestClient) -> None:
    """内置工具删除被拒（400）。"""
    scenes = api_client.get("/api/scenes").json()
    tools = api_client.get(f"/api/tools?scene_id={scenes[0]['id']}").json()
    builtin = next(t for t in tools if t["builtin"])
    resp = api_client.delete(f"/api/tools/{builtin['id']}")
    assert resp.status_code == 400
    assert "不可删除" in resp.json()["detail"]


def test_builtin_bindable_in_flow_publish(api_client: TestClient) -> None:
    """handler 绑定内置工具可通过发布校验（不属于场景但 builtin 放行）。"""
    scene = api_client.post("/api/scenes", json={"name": "测试场景内置", "description": ""}).json()
    flow = api_client.post(
        "/api/flows", json={"scene_id": scene["id"], "name": "内置绑定流程", "description": ""}
    ).json()
    detail = api_client.get(f"/api/flows/{flow['id']}").json()
    draft = detail["draft"]
    tools = api_client.get(f"/api/tools?scene_id={scene['id']}").json()
    kb = next(t for t in tools if t["builtin"])
    for node in draft["nodes"]:
        if node["type"] == "handler":
            node["data"]["tool_ids"] = [kb["id"]]
    api_client.put(f"/api/flows/{flow['id']}", json={"draft": draft})
    resp = api_client.post(f"/api/flows/{flow['id']}/publish")
    assert resp.status_code == 200, resp.json()
    # 清理
    api_client.delete(f"/api/flows/{flow['id']}")
    api_client.delete(f"/api/scenes/{scene['id']}")


class _FakeLLM:
    """模拟 DeepSeek：返回一段随机短答。"""

    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.calls: list[list[dict]] = []

    async def generate(self, messages: list[dict], **kwargs):  # noqa: ANN202
        self.calls.append(messages)
        if self.text is None:
            raise RuntimeError("llm down")
        yield self.text


async def test_kb_search_run_llm_short_answer(monkeypatch) -> None:  # noqa: ANN001
    """模拟检索：LLM 回复截断到 10 字以内。"""
    fake = _FakeLLM("这是随机回复内容很长很长。")
    monkeypatch.setattr(
        "callbot.tools.executors.DeepSeekStreamingLLM",
        lambda **kw: fake,
    )
    out = await kb_search_run("怎么退款？")
    assert len(out) <= 10
    assert out  # 非空
    # 请求携带查询内容
    assert fake.calls and fake.calls[0][-1]["content"] == "怎么退款？"


async def test_kb_search_run_fallback(monkeypatch) -> None:  # noqa: ANN001
    """LLM 不可用 → 随机兜底短答（不抛异常）。"""
    monkeypatch.setattr(
        "callbot.tools.executors.DeepSeekStreamingLLM",
        lambda **kw: _FakeLLM(None),
    )
    out = await kb_search_run("任意问题")
    assert 0 < len(out) <= 10
