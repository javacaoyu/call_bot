"""通话记录 API 测试（WBS 5.3；依赖 docker postgres）。"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from callbot.api.app import create_app
from callbot.data.models import CallRecord, get_engine, save_call_record

# 本次测试写入的记录 id（fixture 收尾清理；教训：测试数据不得污染生产表）
_created_ids: list[UUID] = []


@pytest.fixture()
def api_client() -> TestClient:
    yield TestClient(create_app())
    if _created_ids:
        with Session(get_engine()) as s:
            s.execute(delete(CallRecord).where(CallRecord.id.in_(_created_ids)))
            s.commit()
        _created_ids.clear()


def _make_record(started_offset_s: int = -100) -> CallRecord:
    now = datetime.now(UTC)
    return CallRecord(
        started_at=now,
        ended_at=now,
        duration_s=42,
        status="connected",
        interrupt_count=1,
        transcript=[
            {"role": "bot", "text": "您好。", "ts": 1.0},
            {"role": "user", "text": "你好。", "ts": 3.5},
            {"role": "mark", "text": "客户打断", "ts": 8.0},
        ],
    )


def _save_and_track(record: CallRecord) -> None:
    """落库并登记 id（fixture 收尾按 id 精确删除，不误删真实记录）。"""
    save_call_record(record)
    _created_ids.append(record.id)


def test_list_calls(api_client: TestClient) -> None:
    """列表返回记录（含状态文案与转写气泡）。"""
    _save_and_track(_make_record())
    resp = api_client.get("/api/calls")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    first = data[0]
    assert first["status_text"] == "接通"
    assert first["duration_s"] == 42
    assert first["interrupt_count"] == 1
    assert len(first["transcript"]) == 3
    assert first["transcript"][2]["role"] == "mark"


def test_get_call_detail(api_client: TestClient) -> None:
    """详情返回完整气泡流。"""
    record = _make_record()
    _save_and_track(record)
    resp = api_client.get(f"/api/calls/{record.id}")
    assert resp.status_code == 200
    assert len(resp.json()["transcript"]) == 3


def test_get_call_invalid_id(api_client: TestClient) -> None:
    """非法 ID 422；不存在 404。"""
    assert api_client.get("/api/calls/not-a-uuid").status_code == 422
    assert api_client.get("/api/calls/00000000-0000-0000-0000-000000000000").status_code == 404
