"""火山引擎豆包大模型流式 ASR 云端实现（v3 二进制协议）。

协议要点（官方文档 docs.volcengine.com 大模型流式语音识别 API）：
- wss://openspeech.bytedance.com/api/v3/sauc/bigmodel；
- 鉴权走握手 headers（新版）：X-Api-Key / X-Api-Resource-Id /
  X-Api-Request-Id / X-Api-Sequence(-1) / X-Api-Connect-Id；
- 二进制帧：[4B header][可选 4B sequence][4B payload_size(BE)][payload]；
  header = version(0b0001)<<4|header_size(0b0001), msg_type<<4|flags,
  serialization<<4|compression, 0x00；
- full client request（首帧，JSON）；audio-only（裸 PCM，最后一帧 flags=0010）；
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

_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
_HEADER_BASE = 0x11  # version=1, header_size=1（即 4 字节）

# message types
_MT_FULL_CLIENT = 0b0001
_MT_AUDIO_ONLY = 0b0010
_MT_FULL_SERVER = 0b1001
_MT_ERROR = 0b1111


def encode_full_client_request(payload: dict) -> bytes:
    """构造 full client request 帧（JSON 序列化，无压缩）。"""
    body = json.dumps(payload).encode()
    header = bytes([_HEADER_BASE, _MT_FULL_CLIENT << 4, 0x10, 0x00])
    return header + len(body).to_bytes(4, "big") + body


def encode_audio_packet(data: bytes, last: bool = False) -> bytes:
    """构造 audio-only 帧（裸 PCM；last=True 用 flags=0010 标记最后一包）。"""
    header = bytes([_HEADER_BASE, _MT_AUDIO_ONLY << 4 | (0b0010 if last else 0), 0x00, 0x00])
    return header + len(data).to_bytes(4, "big") + data


def decode_server_packet(raw: bytes) -> tuple[str, bytes] | None:
    """解析服务端帧，返回 (kind, payload)；error 帧返回 None（已记日志）。

    kind: "result"（full server response，payload 为 JSON 原文）；
    layout 均含 4B sequence：header + sequence + payload_size + payload；
    error 帧：header + error_code + error_size + message。
    """
    if len(raw) < 12:
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
    size = int.from_bytes(raw[8:12], "big")
    body = raw[12 : 12 + size]
    try:
        payload = gzip.decompress(body)
    except OSError:
        payload = body
    return ("result", payload)


class VolcStreamingASR(CloudASRBase):
    """火山豆包大模型流式 ASR 云端实现（新控制台 X-Api-Key 鉴权）。"""

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
                    "language": "zh-CN",
                },
                "request": {"model_name": "bigmodel", "enable_punc": True},
            }
        )

    def _encode_audio(self, data: bytes) -> bytes:
        return encode_audio_packet(data)

    def _end_frame(self) -> bytes:
        return encode_audio_packet(b"", last=True)

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
        """关连接并清增量基准（下一轮从空文本重新累计）。"""
        super().reset()
        self._emitted_text = ""
