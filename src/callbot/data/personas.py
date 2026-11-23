"""激活人设查询（WBS 6.1）：编排层会话建立时读取 system prompt。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from callbot.config import Settings
from callbot.data.models import Persona, get_engine
from callbot.orchestration.context import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def get_active_persona_prompt(settings: Settings | None = None) -> str:
    """当前激活人设的 system prompt；无激活人设回退默认文案。"""
    try:
        with Session(get_engine(settings)) as session:
            persona = session.scalars(
                select(Persona).where(Persona.is_active).limit(1)
            ).first()
            if persona is not None:
                return persona.system_prompt
    except Exception:  # noqa: BLE001 - DB 不可用回退默认，不阻断对话
        logger.exception("读取激活人设失败，回退默认")
    return DEFAULT_SYSTEM_PROMPT
