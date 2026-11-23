"""场景管理 API（WBS 6.3）：话术资产组织单元——流程图/人设/工具挂在场景下。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from callbot.data.models import Flow, Persona, Scene, Tool, get_engine

router = APIRouter(prefix="/api", tags=["scenes"])


class SceneIn(BaseModel):
    """新建/编辑场景请求体。"""

    name: str = Field(min_length=1, max_length=64)
    description: str = ""


def _scene_dict(s: Scene) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "created_at": s.created_at.isoformat(),
    }


def get_default_scene(session: Session) -> Scene | None:
    """取默认场景（种子「通用客服」；缺失时取最早创建的场景兜底）。"""
    scene = session.scalars(select(Scene).where(Scene.name == "通用客服")).first()
    if scene is None:
        scene = session.scalars(select(Scene).order_by(Scene.created_at)).first()
    return scene


@router.get("/scenes")
async def list_scenes() -> list[dict]:
    """场景列表（创建时间正序）。"""
    with Session(get_engine()) as session:
        scenes = session.scalars(select(Scene).order_by(Scene.created_at)).all()
        return [_scene_dict(s) for s in scenes]


@router.post("/scenes")
async def create_scene(body: SceneIn) -> dict:
    """新建场景。"""
    scene = Scene(name=body.name, description=body.description)
    with Session(get_engine(), expire_on_commit=False) as session:
        session.add(scene)
        session.commit()
        return _scene_dict(scene)


@router.put("/scenes/{scene_id}")
async def update_scene(scene_id: str, body: SceneIn) -> dict:
    """编辑场景。"""
    try:
        uid = uuid.UUID(scene_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法场景 ID") from None
    with Session(get_engine(), expire_on_commit=False) as session:
        scene = session.get(Scene, uid)
        if scene is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        scene.name = body.name
        scene.description = body.description
        session.commit()
        return _scene_dict(scene)


@router.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: str) -> dict:
    """删除场景：场景下有流程/人设/工具时拒绝（防资产悬挂）。"""
    try:
        uid = uuid.UUID(scene_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法场景 ID") from None
    with Session(get_engine()) as session:
        scene = session.get(Scene, uid)
        if scene is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        flow_count = session.scalars(
            select(Flow.id).where(Flow.scene_id == uid).limit(1)
        ).first()
        persona_count = session.scalars(
            select(Persona.id).where(Persona.scene_id == uid).limit(1)
        ).first()
        tool_count = session.scalars(
            select(Tool.id).where(Tool.scene_id == uid).limit(1)
        ).first()
        if flow_count or persona_count or tool_count:
            raise HTTPException(
                status_code=400,
                detail="场景下存在流程/人设/工具，请先清理后再删除",
            )
        session.delete(scene)
        session.commit()
        return {"deleted": scene_id}
