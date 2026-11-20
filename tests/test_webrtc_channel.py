"""WebRTC 信令校验与会话管理单元测试。"""

from aiortc import RTCPeerConnection

from callbot.channel.webrtc import (
    Session,
    SessionManager,
    _parse_ice_candidate,
    validate_message,
)


def test_validate_offer_valid() -> None:
    """合法 offer 应解析通过。"""
    msg = validate_message('{"type": "offer", "sdp": "v=0"}')
    assert msg is not None
    assert msg["type"] == "offer"


def test_validate_invalid_json() -> None:
    """非法 JSON 返回 None。"""
    assert validate_message("not json") is None


def test_validate_missing_type() -> None:
    """缺 type 字段返回 None。"""
    assert validate_message('{"sdp": "v=0"}') is None


def test_validate_bad_offer_sdp() -> None:
    """offer 缺 sdp 返回 None。"""
    assert validate_message('{"type": "offer"}') is None


def test_validate_ice_candidate() -> None:
    """ICE 消息 candidate 只允许 dict 或 null。"""
    msg = validate_message('{"type": "ice", "candidate": {"candidate": "x"}}')
    assert msg is not None
    assert validate_message('{"type": "ice", "candidate": null}') is not None
    assert validate_message('{"type": "ice", "candidate": 1}') is None


async def test_session_manager_add_remove() -> None:
    """会话登记/查询/移除逻辑。"""
    manager = SessionManager()
    session = Session(peer=RTCPeerConnection(), id="s1")
    manager.add(session)
    assert manager.get("s1") is session
    assert manager.count == 1
    manager.remove("s1")
    assert manager.get("s1") is None
    assert manager.count == 0


def test_parse_ice_host_candidate() -> None:
    """典型 host 候选应解析出全部字段。"""
    cand = _parse_ice_candidate(
        {
            "candidate": (
                "candidate:842163049 1 udp 1677729535 192.168.1.5 54321 "
                "typ host generation 0 ufrag ABCD network-id 1"
            ),
            "sdpMid": "0",
            "sdpMLineIndex": 0,
        }
    )
    assert cand is not None
    assert cand.foundation == "842163049"
    assert cand.component == 1
    assert cand.protocol == "udp"
    assert cand.ip == "192.168.1.5"
    assert cand.port == 54321
    assert cand.type == "host"
    assert cand.sdpMid == "0"
    assert cand.sdpMLineIndex == 0


def test_parse_ice_invalid() -> None:
    """非法候选返回 None。"""
    assert _parse_ice_candidate({"candidate": "not a candidate"}) is None
    assert _parse_ice_candidate({"candidate": "candidate:too short"}) is None
    assert _parse_ice_candidate({}) is None
