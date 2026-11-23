"""行业模板库 API（WBS 6.5）：模板列表 + 一键实例化为场景资产三件套。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from callbot.data.models import Flow, FlowVersion, Persona, Scene, get_engine
from callbot.templates import TEMPLATES, get_template

router = APIRouter(prefix="/api", tags=["templates"])


def _template_summary(t: dict) -> dict:
    """模板摘要（卡片列表数据源：不含完整定义）。"""
    flow = t["flow"]
    nodes = flow.get("nodes", [])
    edges = flow.get("edges", [])
    intent_count = sum(
        1
        for e in edges
        if e.get("from") == "n_intent" and e.get("intent") is not None
    )
    return {
        "key": t["key"],
        "industry": t["industry"],
        "name": t["name"],
        "description": t["description"],
        "persona_name": t["persona"]["name"],
        "node_count": len(nodes),
        "handler_count": sum(1 for n in nodes if n.get("type") == "handler"),
        "intent_count": intent_count,
    }


@router.get("/templates")
async def list_templates() -> list[dict]:
    """模板列表（5 行业预置）。"""
    return [_template_summary(t) for t in TEMPLATES]


@router.post("/templates/{key}/instantiate")
async def instantiate_template(key: str) -> dict:
    """一键实例化：创建场景 + 人设（挂场景）+ 流程图（直接发布 v1）。

    实例化后即独立资产，可在场景编辑器修改/发布/回滚；可重复实例化。
    """
    template = get_template(key)
    if template is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {key}")
    persona = template["persona"]
    now = datetime.now(UTC)
    with Session(get_engine(), expire_on_commit=False) as session:
        scene = Scene(name=template["name"], description=template["description"])
        session.add(scene)
        session.flush()
        p = Persona(
            name=persona["name"],
            description=persona["description"],
            system_prompt=persona["system_prompt"],
            opening=persona.get("opening", ""),
            scene_id=scene.id,
            is_active=False,
        )
        session.add(p)
        flow = Flow(
            scene_id=scene.id,
            name=f"{template['name']}流程",
            description=template["description"],
            draft=template["flow"],
            published=template["flow"],
            version=1,
            published_at=now,
        )
        session.add(flow)
        session.flush()
        session.add(
            FlowVersion(
                flow_id=flow.id,
                version=1,
                definition=template["flow"],
                published_at=now,
            )
        )
        session.commit()
        return {
            "scene_id": str(scene.id),
            "scene_name": scene.name,
            "persona_id": str(p.id),
            "flow_id": str(flow.id),
            "flow_version": flow.version,
        }
