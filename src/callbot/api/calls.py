"""通话记录 API（WBS 5.3）：列表与详情（含转写气泡流）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from callbot.data.models import CallRecord, get_engine

router = APIRouter(prefix="/api", tags=["calls"])

_STATUS_TEXT = {
    "connected": "接通",
    "no_answer": "未接",
    "error": "异常",
}


def _record_dict(record: CallRecord) -> dict:
    return {
        "id": str(record.id),
        "started_at": record.started_at.isoformat(),
        "ended_at": record.ended_at.isoformat(),
        "duration_s": record.duration_s,
        "status": record.status,
        "status_text": _STATUS_TEXT.get(record.status, record.status),
        "interrupt_count": record.interrupt_count,
        "transcript": record.transcript or [],
    }


@router.get("/calls")
async def list_calls(limit: int = 50) -> list[dict]:
    """通话记录列表（按开始时间倒序，默认 50 条）。"""
    with Session(get_engine()) as session:
        records = session.scalars(
            select(CallRecord).order_by(CallRecord.started_at.desc()).limit(limit)
        ).all()
        return [_record_dict(r) for r in records]


@router.get("/calls/{call_id}")
async def get_call(call_id: str) -> dict:
    """单条通话详情（含完整转写气泡流）。"""
    try:
        uid = uuid.UUID(call_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法通话 ID") from None
    with Session(get_engine()) as session:
        record = session.get(CallRecord, uid)
        if record is None:
            raise HTTPException(status_code=404, detail="通话不存在")
        return _record_dict(record)
