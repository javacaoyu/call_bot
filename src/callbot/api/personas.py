"""人设管理 API（WBS 6.1）：Prompt 模板的 CRUD 与激活切换。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from callbot.api.scenes import get_default_scene
from callbot.data.models import Persona, Scene, get_engine

router = APIRouter(prefix="/api", tags=["personas"])


@router.get("/personas/variables")
async def list_variables() -> dict[str, str]:
    """内置可用变量（隐式注入位置：模板中出现即外呼时动态渲染；时间类系统自动注入）。"""
    return {
        "客户姓名": "外呼前选择的客户姓名",
        "电话号码": "外呼前选择的客户手机号",
        "客户备注": "外呼前选择的客户备注",
    }


class PersonaIn(BaseModel):
    """新建/编辑人设的请求体。

    scene_id（6.3）：场景从场景库选择；缺省归默认场景（兼容旧前端，
    6.3.5 起前端为必选下拉）。
    """

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    system_prompt: str = Field(min_length=1)
    opening: str = ""
    scene_id: str | None = None


def _resolve_scene(session: Session, scene_id: str | None) -> Scene:
    """解析场景归属：显式 scene_id 必须存在；缺省取默认场景。"""
    if scene_id is not None:
        try:
            uid = uuid.UUID(scene_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="非法场景 ID") from None
        scene = session.get(Scene, uid)
        if scene is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        return scene
    scene = get_default_scene(session)
    if scene is None:
        raise HTTPException(status_code=500, detail="默认场景缺失，请重启后端完成种子")
    return scene


def _persona_dict(p: Persona, scene: Scene | None = None) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "system_prompt": p.system_prompt,
        "opening": p.opening,
        "is_active": p.is_active,
        "scene_id": str(p.scene_id) if p.scene_id is not None else None,
        "scene_name": scene.name if scene is not None else None,
        "created_at": p.created_at.isoformat(),
    }


@router.get("/personas")
async def list_personas(scene_id: str | None = None) -> list[dict]:
    """人设列表（创建时间正序；可选按场景过滤——外呼选场景时用）。"""
    with Session(get_engine()) as session:
        stmt = select(Persona).order_by(Persona.created_at)
        if scene_id is not None:
            try:
                uid = uuid.UUID(scene_id)
            except ValueError:
                raise HTTPException(status_code=422, detail="非法场景 ID") from None
            stmt = stmt.where(Persona.scene_id == uid)
        personas = session.scalars(stmt).all()
        scenes = {
            s.id: s for s in session.scalars(select(Scene)).all()
        }
        return [_persona_dict(p, scenes.get(p.scene_id)) for p in personas]


@router.post("/personas")
async def create_persona(body: PersonaIn) -> dict:
    """新建人设（不自动激活）。"""
    with Session(get_engine(), expire_on_commit=False) as session:
        scene = _resolve_scene(session, body.scene_id)
        persona = Persona(
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            opening=body.opening,
            scene_id=scene.id,
            is_active=False,
        )
        session.add(persona)
        session.commit()
        return _persona_dict(persona, scene)


@router.put("/personas/{persona_id}")
async def update_persona(persona_id: str, body: PersonaIn) -> dict:
    """编辑人设。"""
    try:
        uid = uuid.UUID(persona_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法人设 ID") from None
    with Session(get_engine(), expire_on_commit=False) as session:
        persona = session.get(Persona, uid)
        if persona is None:
            raise HTTPException(status_code=404, detail="人设不存在")
        scene = _resolve_scene(session, body.scene_id)
        persona.name = body.name
        persona.description = body.description
        persona.system_prompt = body.system_prompt
        persona.opening = body.opening
        persona.scene_id = scene.id
        session.commit()
        return _persona_dict(persona, scene)


@router.delete("/personas/{persona_id}")
async def delete_persona(persona_id: str) -> dict:
    """删除人设（激活中的人设不可删除）。"""
    try:
        uid = uuid.UUID(persona_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法人设 ID") from None
    with Session(get_engine()) as session:
        persona = session.get(Persona, uid)
        if persona is None:
            raise HTTPException(status_code=404, detail="人设不存在")
        if persona.is_active:
            raise HTTPException(status_code=400, detail="激活中的人设不可删除，请先激活其他人设")
        session.delete(persona)
        session.commit()
        return {"deleted": persona_id}


@router.post("/personas/{persona_id}/activate")
async def activate_persona(persona_id: str) -> dict:
    """激活人设（互斥：其他人设置非激活）。"""
    try:
        uid = uuid.UUID(persona_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法人设 ID") from None
    with Session(get_engine(), expire_on_commit=False) as session:
        persona = session.get(Persona, uid)
        if persona is None:
            raise HTTPException(status_code=404, detail="人设不存在")
        session.execute(update(Persona).values(is_active=False))  # 互斥
        persona.is_active = True
        session.commit()
        return _persona_dict(persona)
