"""WebRTC 信令与媒体通道（aiortc）。

流程：浏览器经 WebSocket 发送 offer → 后端创建 RTCPeerConnection 回 answer →
双方交换 ICE → 远端音轨到达后原样环回（验证媒体通道双向可用）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from aiortc import (
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.mediastreams import MediaStreamTrack
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)

SignalMessage = dict[str, Any]


def validate_message(raw: str) -> SignalMessage | None:
    """解析并校验信令消息，非法消息返回 None。

    Args:
        raw: 原始 JSON 字符串。

    Returns:
        校验通过的 dict；JSON 非法、缺 type、字段类型不符时返回 None。
    """
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict) or "type" not in msg:
        return None
    mtype = msg["type"]
    if mtype in ("offer", "answer") and not isinstance(msg.get("sdp"), str):
        return None
    if mtype == "ice" and not isinstance(msg.get("candidate"), (dict, type(None))):
        return None
    return msg


@dataclass
class Session:
    """单路 WebRTC 会话。"""

    peer: RTCPeerConnection
    id: str
    tracks: list[MediaStreamTrack] = field(default_factory=list)


class SessionManager:
    """会话登记、查询与清理。"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        """登记会话。"""
        self._sessions[session.id] = session

    def remove(self, session_id: str) -> None:
        """移除会话（不存在时静默）。"""
        self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> Session | None:
        """按 id 查询会话。"""
        return self._sessions.get(session_id)

    @property
    def count(self) -> int:
        """当前会话数。"""
        return len(self._sessions)


def _parse_ice_candidate(candidate: dict[str, Any]) -> RTCIceCandidate | None:
    """把浏览器 toJSON() 的 candidate 转成 aiortc RTCIceCandidate。

    candidate 里的 `candidate` 字段是 SDP 候选行（如
    ``candidate:foundation 1 udp 2122260223 192.168.1.5 54321 typ host ...``），
    aiortc 1.16 无 from_sdp，需自行解析。解析失败返回 None。

    Args:
        candidate: 浏览器 RTCIceCandidate.toJSON() 的结果。

    Returns:
        解析成功的 RTCIceCandidate；格式不合法时返回 None。
    """
    line = candidate.get("candidate")
    if not isinstance(line, str) or not line.startswith("candidate:"):
        return None
    parts = line[len("candidate:") :].split()
    if len(parts) < 8:
        return None
    foundation, component, protocol, priority, ip, port, _, ctype = parts[:8]
    related_address: str | None = None
    related_port: int | None = None
    tcp_type: str | None = None
    i = 8
    while i < len(parts):
        if parts[i] == "raddr" and i + 1 < len(parts):
            related_address = parts[i + 1]
            i += 2
        elif parts[i] == "rport" and i + 1 < len(parts):
            related_port = int(parts[i + 1])
            i += 2
        elif parts[i] == "tcptype" and i + 1 < len(parts):
            tcp_type = parts[i + 1]
            i += 2
        else:
            # generation / ufrag / network-id 等成对字段跳过
            i += 2
    return RTCIceCandidate(
        component=int(component),
        foundation=foundation,
        ip=ip,
        port=int(port),
        priority=int(priority),
        protocol=protocol,
        type=ctype,
        relatedAddress=related_address,
        relatedPort=related_port,
        sdpMid=candidate.get("sdpMid"),
        sdpMLineIndex=candidate.get("sdpMLineIndex"),
        tcpType=tcp_type,
    )


def _attach_echo(session: Session, manager: SessionManager) -> None:
    """为会话挂载音轨环回与连接状态清理。"""
    pc = session.peer

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        logger.info("收到远端音轨 kind=%s", track.kind)
        session.tracks.append(track)
        # 回声环回：把收到的音轨原样发回浏览器
        pc.addTrack(track)

    @pc.on("connectionstatechange")
    async def on_state() -> None:
        if pc.connectionState in ("failed", "closed"):
            manager.remove(session.id)


async def handle_signaling(websocket: WebSocket, manager: SessionManager) -> None:
    """处理一路浏览器信令连接（offer/answer/ICE），内含媒体环回。

    Args:
        websocket: 已 accept 的信令连接。
        manager: 会话管理器。
    """
    session: Session | None = None
    try:
        while True:
            raw = await websocket.receive_text()
            msg = validate_message(raw)
            if msg is None:
                await websocket.send_text(
                    json.dumps({"type": "error", "detail": "bad message"})
                )
                continue

            mtype = msg["type"]
            if mtype == "offer":
                pc = RTCPeerConnection()
                session = Session(peer=pc, id=str(id(pc)))
                manager.add(session)
                _attach_echo(session, manager)
                await pc.setRemoteDescription(
                    RTCSessionDescription(sdp=msg["sdp"], type="offer")
                )
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                assert pc.localDescription is not None
                await websocket.send_text(
                    json.dumps({"type": "answer", "sdp": pc.localDescription.sdp})
                )
            elif mtype == "ice":
                candidate = msg.get("candidate")
                if session is not None and isinstance(candidate, dict):
                    cand = _parse_ice_candidate(candidate)
                    if cand is not None:
                        await session.peer.addIceCandidate(cand)
    except WebSocketDisconnect:
        pass
    finally:
        if session is not None:
            await session.peer.close()
            manager.remove(session.id)
