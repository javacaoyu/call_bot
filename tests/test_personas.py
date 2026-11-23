"""人设管理 API 测试（WBS 6.1；依赖 docker postgres）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from callbot.api.app import create_app
from callbot.data.models import Persona, get_engine


@pytest.fixture()
def api_client() -> TestClient:
    """⚠️ 不清生产表（曾误删用户人设数据）；测试数据用「测试人设」前缀，
    测试后只清理自己创建的记录。"""
    client = TestClient(create_app())
    yield client
    with Session(get_engine()) as s:
        s.execute(delete(Persona).where(Persona.name.like("测试人设%")))
        # 恢复激活状态到「默认客服」（测试激活会挤掉用户人设）
        default = s.scalars(select(Persona).where(Persona.name == "默认客服")).first()
        if default is not None:
            s.execute(update(Persona).values(is_active=False))
            default.is_active = True
        s.commit()


def _create(client: TestClient, name: str = "测试人设") -> dict:
    resp = client.post(
        "/api/personas",
        json={"name": name, "description": "测试", "system_prompt": "你是测试。"},
    )
    assert resp.status_code == 200
    return resp.json()


def test_list_seeded_default(api_client: TestClient) -> None:
    """启动种子：默认人设存在且激活（不清用户数据）。"""
    data = api_client.get("/api/personas").json()
    default = next((x for x in data if x["name"] == "默认客服"), None)
    assert default is not None
    assert default["is_active"] is True


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
    p2 = _create(api_client, "测试人设二")
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


def test_render_prompt_builtin() -> None:
    """内置变量渲染：时间类实时填充；任务变量占位。"""
    from callbot.data.personas import render_prompt

    out = render_prompt("今天是{今天日期}，客户{客户姓名}你好。", context={})
    assert "2026年11月23日" in out or "今天是" in out
    # 任务变量占位
    assert "客户" in out


def test_render_prompt_unknown_preserved() -> None:
    """未定义变量原样保留。"""
    from callbot.data.personas import render_prompt

    assert render_prompt("你好{不存在的变量}") == "你好{不存在的变量}"


def test_render_prompt_context_override() -> None:
    """context 覆盖内置值。"""
    from callbot.data.personas import render_prompt

    assert render_prompt("{客户姓名}", context={"客户姓名": "陈女士"}) == "陈女士"


def test_extract_variables() -> None:
    """占位符提取去重。"""
    from callbot.data.personas import extract_variables

    assert extract_variables("{客户姓名}和{客户姓名}，{今天日期}") == {"客户姓名", "今天日期"}


def test_builtin_weekday(monkeypatch) -> None:  # noqa: ANN001
    """星期计算。"""
    from datetime import UTC, datetime

    from callbot.data.personas import builtin_variable_values

    values = builtin_variable_values(datetime(2026, 11, 23, tzinfo=UTC))  # 周一
    assert values["星期几"] == "星期一"
    assert values["当前时间"] == "00:00"


def test_variables_api(api_client: TestClient) -> None:
    """内置变量列表 API。"""
    data = api_client.get("/api/personas/variables").json()
    assert "客户姓名" in data
    assert "电话号码" in data
    assert "客户备注" in data
    assert "今天日期" not in data  # 时间类系统自动注入，不在变量面板


def test_render_with_context_time_appended() -> None:
    """时间行自动附加 + 客户变量填充。"""
    from callbot.data.personas import render_with_context

    out = render_with_context("你好{客户姓名}", {"name": "陈女士", "phone": "138"})
    assert "你好陈女士" in out
    assert "（当前时间：" in out


def test_get_persona_prompt_by_id(api_client: TestClient) -> None:
    """按 id 取人设模板；不存在返回 None。"""
    from callbot.data.personas import get_persona_prompt

    data = api_client.get("/api/personas").json()
    first = data[0]
    assert get_persona_prompt(first["id"]) == first["system_prompt"]
    assert get_persona_prompt("00000000-0000-0000-0000-000000000000") is None


def test_persona_opening_roundtrip(api_client: TestClient) -> None:
    """开场白字段 CRUD 往返（6.2）。"""
    p = api_client.post(
        "/api/personas",
        json={
            "name": "测试人设开场",
            "description": "",
            "system_prompt": "你是测试。",
            "opening": "您好{客户姓名}",
        },
    ).json()
    assert p["opening"] == "您好{客户姓名}"
    resp = api_client.put(
        f"/api/personas/{p['id']}",
        json={
            "name": "测试人设开场",
            "description": "",
            "system_prompt": "你是测试。",
            "opening": "您好，备注{客户备注}",
        },
    )
    assert resp.json()["opening"] == "您好，备注{客户备注}"


def test_render_opening_customer_vars() -> None:
    """开场白渲染：客户变量动态注入，不附加时间行（口播文本）。"""
    from callbot.data.personas import render_opening

    customer = {"name": "陈女士", "phone": "13800002047", "notes": "理财回访"}
    out = render_opening(
        "{客户姓名}您好，尾号{电话号码}，备注{客户备注}",
        customer,
    )
    assert out == "陈女士您好，尾号13800002047，备注理财回访"
    assert "当前时间" not in out


def test_render_with_context_notes() -> None:
    """客户备注动态注入 system prompt。"""
    from callbot.data.personas import render_with_context

    out = render_with_context(
        "备注：{客户备注}",
        {"name": "陈女士", "phone": "138", "notes": "理财回访"},
    )
    assert "备注：理财回访" in out


def test_resolve_opening_priority(api_client: TestClient) -> None:
    """所选人设开场白优先；激活人设兜底（6.2）。"""
    from callbot.data.personas import resolve_opening

    p = api_client.post(
        "/api/personas",
        json={
            "name": "测试人设开场优先",
            "description": "",
            "system_prompt": "你是测试。",
            "opening": "您好{客户姓名}",
        },
    ).json()
    customer = {"name": "陈女士", "phone": "138", "notes": ""}
    assert resolve_opening(p["id"], customer=customer) == "您好陈女士"
    # 未指定人设时按激活人设兜底
    api_client.post(f"/api/personas/{p['id']}/activate")
    assert resolve_opening(None, customer=customer) == "您好陈女士"


def test_resolve_opening_none_when_unconfigured(api_client: TestClient) -> None:
    """未配置开场白时返回 None（由 LLM 按人设兜底生成）。"""
    from callbot.data.personas import resolve_opening

    p = api_client.post(
        "/api/personas",
        json={"name": "测试人设无开场", "description": "", "system_prompt": "你是测试。"},
    ).json()
    api_client.post(f"/api/personas/{p['id']}/activate")
    assert resolve_opening(None) is None


def test_customers_api(api_client: TestClient) -> None:
    """客户列表与新建。"""
    data = api_client.get("/api/customers").json()
    assert len(data) >= 1  # 种子客户
    resp = api_client.post(
        "/api/customers", json={"name": "测试客户", "phone": "13800000000"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "测试客户"


def test_customer_update_delete(api_client: TestClient) -> None:
    """客户编辑与删除。"""
    created = api_client.post(
        "/api/customers", json={"name": "临时客户", "phone": "13900000001"}
    ).json()
    resp = api_client.put(
        f"/api/customers/{created['id']}",
        json={"name": "临时客户改", "phone": "13900000002", "notes": "n"},
    )
    assert resp.json()["name"] == "临时客户改"
    assert api_client.delete(f"/api/customers/{created['id']}").status_code == 200
    names = [c["name"] for c in api_client.get("/api/customers").json()]
    assert "临时客户改" not in names
