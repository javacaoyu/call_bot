"""通话记录 API 测试（WBS 5.3；依赖 docker postgres）。"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from callbot.api.app import create_app
from callbot.data.models import CallRecord, save_call_record


@pytest.fixture()
def api_client() -> TestClient:
    return TestClient(create_app())


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


def test_list_calls(api_client: TestClient) -> None:
    """列表返回记录（含状态文案与转写气泡）。"""
    save_call_record(_make_record())
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
    save_call_record(record)
    resp = api_client.get(f"/api/calls/{record.id}")
    assert resp.status_code == 200
    assert len(resp.json()["transcript"]) == 3


def test_get_call_invalid_id(api_client: TestClient) -> None:
    """非法 ID 422；不存在 404。"""
    assert api_client.get("/api/calls/not-a-uuid").status_code == 422
    assert api_client.get("/api/calls/00000000-0000-0000-0000-000000000000").status_code == 404
