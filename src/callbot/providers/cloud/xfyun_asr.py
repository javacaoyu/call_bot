"""讯飞语音听写（IAT V2）流式 ASR 云端实现。

协议要点（官方文档 xfyun.cn/doc/spark/spark_zh_iat.html）：
- wss://iat-api.xfyun.cn/v2/iat，鉴权走 URL 参数：hmac-sha256 签名
  （host/date/request-line 三要素）→ authorization base64 → query 拼接；
- JSON 帧：status 0 参数帧 → status 1 音频帧（base64）→ status 2 结束帧；
- 响应 JSON：data.result.ws[].cw[].w 为增量词，result.ls=True 为句尾。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from email.utils import formatdate
from urllib.parse import urlencode

from callbot.providers.asr import ASRResult
from callbot.providers.cloud.base_cloud import CloudASRBase

logger = logging.getLogger(__name__)

_HOST = "iat-api.xfyun.cn"
_PATH = "/v2/iat"
_AUDIO_META = {"format": "audio/L16;rate=16000", "encoding": "raw"}


def sign_iat(host: str, path: str, date: str, api_secret: str) -> str:
    """IAT 鉴权签名：三要素（host/date/request-line）hmac-sha256 → base64。"""
    signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
    return base64.b64encode(
        hmac.new(api_secret.encode(), signature_origin.encode(), hashlib.sha256).digest()
    ).decode()


def build_iat_url(host: str, path: str, api_key: str, api_secret: str) -> str:
    """构造带鉴权 query 的 IAT WebSocket URL（纯函数，便于单测）。

    authorization 串（api_key/algorithm/headers/signature）整体 base64 进 query。
    """
    date = formatdate(usegmt=True)
    signature = sign_iat(host, path, date, api_secret)
    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode()).decode()
    query = urlencode({"authorization": authorization, "date": date, "host": host})
    return f"wss://{host}{path}?{query}"


def build_iat_frame(status: int, audio: bytes = b"") -> bytes:
    """构造 IAT JSON 帧（status: 0 参数 / 1 音频 / 2 结束）。"""
    payload = {
        "data": {
            "status": status,
            "format": _AUDIO_META["format"],
            "encoding": _AUDIO_META["encoding"],
            "audio": base64.b64encode(audio).decode(),
        }
    }
    return json.dumps(payload).encode()


def parse_iat_message(raw: bytes | str) -> ASRResult | None:
    """解析 IAT 响应：拼接增量词，ls=True 标记句尾。"""
    if isinstance(raw, bytes):
        raw = raw.decode()
    msg = json.loads(raw)
    if msg.get("code") != 0:
        logger.error("讯飞 IAT 错误 %s: %s", msg.get("code"), msg.get("message"))
        return None
    result = (msg.get("data") or {}).get("result") or {}
    ws = result.get("ws") or []
    if not ws:
        return None
    text = "".join(
        w.get("w", "") for item in ws for w in (item.get("cw") or []) if w.get("w")
    )
    if not text:
        return None
    return ASRResult(text=text, is_final=bool(result.get("ls")))


class XfyunStreamingASR(CloudASRBase):
    """讯飞流式语音听写（IAT V2）云端实现。"""

    def __init__(
        self,
        app_id: str,
        api_key: str,
        api_secret: str,
        host: str = _HOST,
    ) -> None:
        super().__init__()
        self._app_id = app_id
        self._api_key = api_key
        self._api_secret = api_secret
        self._host = host

    def _build_url(self) -> str:
        return build_iat_url(self._host, _PATH, self._api_key, self._api_secret)

    def _start_frame(self) -> bytes:
        return json.dumps(
            {
                "common": {"app_id": self._app_id},
                "business": {
                    "language": "zh_cn",
                    "domain": "iat",
                    "accent": "mandarin",
                },
                "data": {**_AUDIO_META, "status": 0, "audio": ""},
            }
        ).encode()

    def _encode_audio(self, data: bytes) -> bytes:
        return build_iat_frame(1, data)

    def _end_frame(self) -> bytes:
        return build_iat_frame(2)

    def _parse_message(self, raw: bytes | str) -> ASRResult | None:
        return parse_iat_message(raw)
