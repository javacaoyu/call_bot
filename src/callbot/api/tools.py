"""工具库 API（WBS 6.3）：场景工具库——HTTP 配置工具 CRUD + 代码插件清单。"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from callbot.data.models import Scene, Tool, get_engine
from callbot.tools.loader import list_plugins

router = APIRouter(prefix="/api", tags=["tools"])


class ToolIn(BaseModel):
    """新建/编辑工具请求体。

    kind=http：config = {method, url, headers, params: [{name, type, required, description}]}
    kind=plugin：config = {plugin: 插件名}
    """

    scene_id: str
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    kind: Literal["http", "plugin"] = "http"
    config: dict = Field(default_factory=dict)


def _tool_dict(t: Tool) -> dict:
    return {
        "id": str(t.id),
        "scene_id": str(t.scene_id) if t.scene_id is not None else None,
        "name": t.name,
        "description": t.description,
        "kind": t.kind,
        "config": t.config,
        "builtin": t.kind == "builtin",
        "created_at": t.created_at.isoformat(),
    }


def _get_scene(session: Session, scene_id: str) -> Scene:
    """校验场景存在；不存在 404。"""
    try:
        uid = uuid.UUID(scene_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法场景 ID") from None
    scene = session.get(Scene, uid)
    if scene is None:
        raise HTTPException(status_code=404, detail="场景不存在")
    return scene


@router.get("/tools")
async def list_tools(scene_id: str) -> list[dict]:
    """按场景列出工具：本场景工具 ∪ 内置基础工具（所有场景默认提供）。"""
    from sqlalchemy import or_

    with Session(get_engine()) as session:
        _get_scene(session, scene_id)
        tools = session.scalars(
            select(Tool)
            .where(
                or_(
                    Tool.scene_id == uuid.UUID(scene_id),
                    Tool.kind == "builtin",
                )
            )
            .order_by(Tool.created_at)
        ).all()
        return [_tool_dict(t) for t in tools]


@router.post("/tools")
async def create_tool(body: ToolIn) -> dict:
    """新建工具（挂到场景）。"""
    with Session(get_engine(), expire_on_commit=False) as session:
        _get_scene(session, body.scene_id)
        tool = Tool(
            scene_id=uuid.UUID(body.scene_id),
            name=body.name,
            description=body.description,
            kind=body.kind,
            config=body.config,
        )
        session.add(tool)
        session.commit()
        return _tool_dict(tool)


@router.put("/tools/{tool_id}")
async def update_tool(tool_id: str, body: ToolIn) -> dict:
    """编辑工具（名称/说明/kind/配置；场景归属不可改——换场景请重建）。"""
    try:
        uid = uuid.UUID(tool_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法工具 ID") from None
    with Session(get_engine(), expire_on_commit=False) as session:
        tool = session.get(Tool, uid)
        if tool is None:
            raise HTTPException(status_code=404, detail="工具不存在")
        _get_scene(session, body.scene_id)  # 校验场景仍存在（保持归属一致性）
        tool.name = body.name
        tool.description = body.description
        tool.kind = body.kind
        tool.config = body.config
        session.commit()
        return _tool_dict(tool)


@router.delete("/tools/{tool_id}")
async def delete_tool(tool_id: str) -> dict:
    """删除工具（内置基础工具不可删除）。"""
    try:
        uid = uuid.UUID(tool_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法工具 ID") from None
    with Session(get_engine()) as session:
        tool = session.get(Tool, uid)
        if tool is None:
            raise HTTPException(status_code=404, detail="工具不存在")
        if tool.kind == "builtin":
            raise HTTPException(status_code=400, detail="内置基础工具不可删除")
        session.delete(tool)
        session.commit()
        return {"deleted": tool_id}


@router.get("/tools/plugins")
async def list_tool_plugins() -> list[dict]:
    """已加载的代码插件清单（WebUI「从插件导入」数据源）。"""
    return list_plugins()
