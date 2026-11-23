"""话术流程图 API（WBS 6.3）：草稿/发布/回滚。

发布 = 结构校验 + 工具绑定校验 → 快照 + 版本+1；
回滚 = 历史快照重新发布为新版本（历史只增不改，全程留痕）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from callbot.data.models import Flow, FlowVersion, Scene, Tool, get_engine
from callbot.flow.definitions import build_default_flow, validate_flow_definition

router = APIRouter(prefix="/api", tags=["flows"])


class FlowCreate(BaseModel):
    """新建流程请求体（一场景一流程）。"""

    scene_id: str
    name: str = Field(min_length=1, max_length=64)
    description: str = ""


class FlowDraft(BaseModel):
    """保存草稿请求体。"""

    name: str | None = Field(default=None, max_length=64)
    description: str | None = None
    draft: dict | None = None


def _flow_summary(f: Flow) -> dict:
    draft = f.draft or {}
    return {
        "id": str(f.id),
        "scene_id": str(f.scene_id),
        "name": f.name,
        "description": f.description,
        "version": f.version,
        "published_at": f.published_at.isoformat() if f.published_at else None,
        "has_unpublished_changes": f.draft != f.published,
        "node_count": len(draft.get("nodes", [])),
        "edge_count": len(draft.get("edges", [])),
    }


def _get_flow(session: Session, flow_id: str) -> Flow:
    try:
        uid = uuid.UUID(flow_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法流程 ID") from None
    flow = session.get(Flow, uid)
    if flow is None:
        raise HTTPException(status_code=404, detail="流程不存在")
    return flow


def _validate_tool_bindings(session: Session, flow: Flow, definition: dict) -> list[str]:
    """发布校验：handler 绑定的工具必须存在于本场景工具库或为内置工具。"""
    from sqlalchemy import or_

    scene_tool_ids = {
        str(t)
        for t in session.scalars(
            select(Tool.id).where(
                or_(
                    Tool.scene_id == flow.scene_id,
                    Tool.kind == "builtin",
                )
            )
        )
    }
    errors: list[str] = []
    for node in definition.get("nodes", []):
        if node.get("type") != "handler":
            continue
        for tool_id in (node.get("data") or {}).get("tool_ids", []):
            if tool_id not in scene_tool_ids:
                errors.append(f"handler「{node['id']}」绑定的工具不存在于本场景: {tool_id}")
    return errors


@router.get("/flows")
async def list_flows(scene_id: str) -> list[dict]:
    """按场景列出流程（scene_id 必填）。"""
    with Session(get_engine()) as session:
        flows = session.scalars(
            select(Flow)
            .where(Flow.scene_id == uuid.UUID(scene_id))
            .order_by(Flow.created_at)
        ).all()
        return [_flow_summary(f) for f in flows]


@router.post("/flows")
async def create_flow(body: FlowCreate) -> dict:
    """新建流程（初始草稿 = 默认流程模板；一场景一流程）。"""
    with Session(get_engine(), expire_on_commit=False) as session:
        scene = session.get(Scene, uuid.UUID(body.scene_id))
        if scene is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        existing = session.scalars(
            select(Flow).where(Flow.scene_id == scene.id).limit(1)
        ).first()
        if existing is not None:
            raise HTTPException(status_code=400, detail="该场景已有流程图（一场景一流程）")
        flow = Flow(
            scene_id=scene.id,
            name=body.name,
            description=body.description,
            draft=build_default_flow(),
        )
        session.add(flow)
        session.commit()
        return _flow_summary(flow)


@router.get("/flows/{flow_id}")
async def get_flow(flow_id: str) -> dict:
    """流程详情（草稿 + 发布快照 + 版本）。"""
    with Session(get_engine()) as session:
        flow = _get_flow(session, flow_id)
        return {
            **_flow_summary(flow),
            "draft": flow.draft,
            "published": flow.published,
        }


@router.get("/flows/{flow_id}/versions")
async def list_flow_versions(flow_id: str) -> list[dict]:
    """发布历史（回滚下拉数据源；倒序）。"""
    with Session(get_engine()) as session:
        flow = _get_flow(session, flow_id)
        versions = session.scalars(
            select(FlowVersion)
            .where(FlowVersion.flow_id == flow.id)
            .order_by(FlowVersion.version.desc())
        ).all()
        return [
            {
                "version": v.version,
                "published_at": v.published_at.isoformat(),
                "node_count": len(v.definition.get("nodes", [])),
                "edge_count": len(v.definition.get("edges", [])),
            }
            for v in versions
        ]


@router.put("/flows/{flow_id}")
async def save_draft(flow_id: str, body: FlowDraft) -> dict:
    """保存草稿（不做结构校验——编辑器自由；发布时严格校验）。"""
    with Session(get_engine(), expire_on_commit=False) as session:
        flow = _get_flow(session, flow_id)
        if body.name is not None:
            flow.name = body.name
        if body.description is not None:
            flow.description = body.description
        if body.draft is not None:
            flow.draft = body.draft
        session.commit()
        return _flow_summary(flow)


@router.delete("/flows/{flow_id}")
async def delete_flow(flow_id: str) -> dict:
    """删除流程（连同发布历史）。"""
    with Session(get_engine()) as session:
        flow = _get_flow(session, flow_id)
        session.delete(flow)
        session.commit()
        return {"deleted": flow_id}


@router.post("/flows/{flow_id}/publish")
async def publish_flow(flow_id: str) -> dict:
    """发布草稿：结构校验 + 工具绑定校验 → 快照 + 版本+1。"""
    with Session(get_engine(), expire_on_commit=False) as session:
        flow = _get_flow(session, flow_id)
        definition = flow.draft or {}
        errors = validate_flow_definition(definition)
        errors += _validate_tool_bindings(session, flow, definition)
        if errors:
            raise HTTPException(status_code=400, detail="；".join(errors))
        now = datetime.now(UTC)
        flow.published = definition
        flow.version += 1
        flow.published_at = now
        session.add(
            FlowVersion(
                flow_id=flow.id,
                version=flow.version,
                definition=definition,
                published_at=now,
            )
        )
        session.commit()
        return _flow_summary(flow)


@router.post("/flows/{flow_id}/rollback/{version}")
async def rollback_flow(flow_id: str, version: int) -> dict:
    """回滚：历史快照重新发布为新版本（历史只增不改）。"""
    with Session(get_engine(), expire_on_commit=False) as session:
        flow = _get_flow(session, flow_id)
        snapshot = session.scalars(
            select(FlowVersion)
            .where(FlowVersion.flow_id == flow.id, FlowVersion.version == version)
        ).first()
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")
        now = datetime.now(UTC)
        flow.published = snapshot.definition
        flow.draft = snapshot.definition  # 草稿同步回历史定义（编辑器从回滚点继续）
        flow.version += 1
        flow.published_at = now
        session.add(
            FlowVersion(
                flow_id=flow.id,
                version=flow.version,
                definition=snapshot.definition,
                published_at=now,
            )
        )
        session.commit()
        return _flow_summary(flow)
