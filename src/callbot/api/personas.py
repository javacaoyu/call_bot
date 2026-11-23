"""人设管理 API（WBS 6.1）：Prompt 模板的 CRUD 与激活切换。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from callbot.data.models import Persona, get_engine

router = APIRouter(prefix="/api", tags=["personas"])


class PersonaIn(BaseModel):
    """新建/编辑人设的请求体。"""

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    system_prompt: str = Field(min_length=1)


def _persona_dict(p: Persona) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "system_prompt": p.system_prompt,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat(),
    }


@router.get("/personas")
async def list_personas() -> list[dict]:
    """人设列表（创建时间正序）。"""
    with Session(get_engine()) as session:
        personas = session.scalars(select(Persona).order_by(Persona.created_at)).all()
        return [_persona_dict(p) for p in personas]


@router.post("/personas")
async def create_persona(body: PersonaIn) -> dict:
    """新建人设（不自动激活）。"""
    persona = Persona(
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        is_active=False,
    )
    with Session(get_engine(), expire_on_commit=False) as session:
        session.add(persona)
        session.commit()
        return _persona_dict(persona)


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
        persona.name = body.name
        persona.description = body.description
        persona.system_prompt = body.system_prompt
        session.commit()
        return _persona_dict(persona)


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
