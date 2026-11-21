"""火山引擎豆包大模型流式 ASR 云端实现（v3 二进制协议）。

协议要点（官方《豆包语音》文档 5.1.2.8，2026-11 版）：
- wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async（双向流式优化版）；
- 鉴权走握手 headers（新版）：X-Api-Key / X-Api-Resource-Id /
  X-Api-Request-Id / X-Api-Sequence(-1) / X-Api-Connect-Id；
- 二进制帧：[4B header][4B payload_size(BE)][payload]；
  header = version(0b0001)<<4|header_size(0b0001), msg_type<<4|flags,
  serialization<<4|compression, 0x00；
- full client request（首帧，JSON **Gzip 压缩**）；audio-only（**Gzip 压缩**
  的 PCM，最后一帧 flags=0010）——⚠️ 音频必须 Gzip，服务端按压缩约定解包；
- 响应：full server response（带 4B sequence，payload 为 gzip JSON，
  result.text 为整段文本——增量取与已发文本的前缀差）；error 帧独立布局。
"""

from __future__ import annotations

import gzip
import json
import logging
import uuid

from callbot.providers.asr import ASRResult
from callbot.providers.cloud.base_cloud import CloudASRBase

logger = logging.getLogger(__name__)

_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
_HEADER_BASE = 0x11  # version=1, header_size=1（即 4 字节）

# message types
_MT_FULL_CLIENT = 0b0001
_MT_AUDIO_ONLY = 0b0010
_MT_FULL_SERVER = 0b1001
_MT_ERROR = 0b1111


def encode_full_client_request(payload: dict) -> bytes:
    """构造 full client request 帧（JSON 序列化 + Gzip 压缩）。"""
    body = gzip.compress(json.dumps(payload).encode())
    header = bytes([_HEADER_BASE, _MT_FULL_CLIENT << 4, 0x11, 0x00])
    return header + len(body).to_bytes(4, "big") + body


def encode_audio_packet(data: bytes, last: bool = False) -> bytes:
    """构造 audio-only 帧（Gzip 压缩的 PCM；last=True 用 flags=0010 标记末包）。"""
    header = bytes(
        [_HEADER_BASE, _MT_AUDIO_ONLY << 4 | (0b0010 if last else 0), 0x01, 0x00]
    )
    body = gzip.compress(data)
    return header + len(body).to_bytes(4, "big") + body


def decode_server_packet(raw: bytes) -> tuple[str, bytes] | None:
    """解析服务端帧，返回 (kind, payload)；error 帧返回 None（已记日志）。

    kind: "result"（full server response，payload 为 JSON 原文）。
    layout（2026-11 实测）：flags=0011（最后一包）带 4B sequence，其余不带；
    error 帧：header + error_code + error_size + message。

    采用自适应解析：sequence 有无 × gzip 与否全组合尝试，JSON 能解析即命中
    ——协议细节以服务端实际行为为准，失败时 hex 日志留证。
    """
    if len(raw) < 8:
        return None
    msg_type = raw[1] >> 4
    if msg_type == _MT_ERROR:
        code = int.from_bytes(raw[4:8], "big")
        size = int.from_bytes(raw[8:12], "big")
        message = raw[12 : 12 + size].decode("utf-8", errors="replace")
        logger.error("火山 ASR 错误 %d: %s", code, message)
        return None
    if msg_type != _MT_FULL_SERVER:
        return None
    flags = raw[1] & 0x0F
    # 候选布局（size 偏移, body 偏移）：flags=0011 尾包带 4B sequence，其余不带；
    # 以 flags 指示的布局优先，另一种兜底
    offsets = (
        [(8, 12), (4, 8)] if flags == 0b0011 else [(4, 8), (8, 12)]
    )
    for size_off, body_off in offsets:
        if len(raw) < size_off + 4:
            continue
        size = int.from_bytes(raw[size_off : size_off + 4], "big")
        if size <= 0 or body_off + size > len(raw):
            continue
        body = raw[body_off : body_off + size]
        for candidate in _payload_candidates(body, raw[2] & 0x0F == 1):
            if _looks_like_json(candidate):
                return ("result", candidate)
    logger.warning("火山 ASR 响应帧无法解析: len=%d hex=%s", len(raw), raw[:24].hex(" "))
    return None


def _payload_candidates(body: bytes, prefer_gzip: bool) -> list[bytes]:
    """按 header 压缩位给出候选 payload（偏好序：指定方式 → 另一种）。"""
    ordered = (gzip.decompress, lambda b: b) if prefer_gzip else (lambda b: b, gzip.decompress)
    out: list[bytes] = []
    for fn in ordered:
        try:
            out.append(fn(body))
        except OSError:
            pass
    return out


def _looks_like_json(payload: bytes) -> bool:
    """JSON 有效性探测（快速，不抛异常）。"""
    if not payload or payload[0] not in (ord("{"), ord("[")):
        return False
    try:
        json.loads(payload)
        return True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


class VolcStreamingASR(CloudASRBase):
    """火山豆包大模型流式 ASR 云端实现（新控制台 X-Api-Key 鉴权）。

    长连接模式：flush 只发静音触发服务端判停（推尾字），连接跨轮复用——
    用户停顿后继续说时音频直接续传，无重连延迟（实测教训）。
    """

    _keep_connection = True

    def __init__(
        self,
        api_key: str,
        resource_id: str = "volc.seedasr.sauc.duration",
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._resource_id = resource_id
        self._connect_id = uuid.uuid4().hex
        self._emitted_text = ""  # 已推送的整段文本（增量 = 前缀差）

    def _build_url(self) -> str:
        return _URL

    def _handshake_headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": uuid.uuid4().hex,
            "X-Api-Sequence": "-1",
            "X-Api-Connect-Id": self._connect_id,
        }

    def _start_frame(self) -> bytes:
        return encode_full_client_request(
            {
                "user": {"uid": "callbot"},
                "audio": {
                    "format": "pcm",
                    "codec": "raw",
                    "rate": 16000,
                    "bits": 16,
                    "channel": 1,
                    # 注意：language 仅流式输入模式（nostream）支持，
                    # 双向流式不传（传了服务端可能拒绝）
                },
                "request": {"model_name": "bigmodel", "enable_punc": True},
            }
        )

    def _encode_audio(self, data: bytes) -> bytes:
        return encode_audio_packet(data)

    def _end_frame(self) -> bytes:
        return encode_audio_packet(b"", last=True)

    def _final_frames(self) -> list[bytes]:
        """判停前补 1.2s 静音流（服务端 end_window_size=800ms 判停释放尾字）。"""
        silence = b"\x00" * (16000 * 2 * 600 // 1000)  # 600ms @16k PCM16
        return [encode_audio_packet(silence), encode_audio_packet(silence)]

    def _parse_message(self, raw: bytes | str) -> ASRResult | None:
        if not isinstance(raw, bytes):
            return None
        parsed = decode_server_packet(raw)
        if parsed is None:
            return None
        kind, payload = parsed
        if kind != "result":
            return None
        data = json.loads(payload)
        full_text = (data.get("result") or {}).get("text", "")
        if not full_text or full_text == self._emitted_text:
            return None
        # 增量 = 前缀差；服务端修正（非前缀）时重发全量
        delta = (
            full_text[len(self._emitted_text) :]
            if full_text.startswith(self._emitted_text)
            else full_text
        )
        self._emitted_text = full_text
        return ASRResult(text=delta, is_final=False)

    def reset(self) -> None:
        """软重置：长连接下不关连接、不清增量基准。

        服务端 result.text 是会话累计文本，前缀差依赖 _emitted_text 保持；
        连接由引擎 stop 后的进程生命周期自然回收。
        """
