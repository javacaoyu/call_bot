"""阿里云智能语音交互流式 TTS（FlowingSpeechSynthesizer）云端实现。

协议要点（官方 SDK alibabacloud-nls-python-sdk 流式合成）：
- wss://nls-gateway-<region>.aliyuncs.com/ws/v1?token=xxx（临时 token 鉴权，
  token 可直配 params.token，或用 AK/SK 经 CreateToken RPC 签名获取）；
- 消息：StartSynthesis（header{namespace=FlowingSpeechSynthesizer, appkey} +
  payload{voice/format/sample_rate/text...}）→ SynthesisStarted →
  二进制音频帧（pcm）→ StopSynthesis → SynthesisCompleted；
- 单段场景：文本随 Start 全量发出，收到 Started 后立即 Stop 收尾。

已知代价：每段一个 WS 连接（协议一个连接一个合成任务），连接 ~200ms；
token 结果缓存复用。延迟优化留待阶段 9。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from callbot.engine.frames import AudioFrame
from callbot.engine.text import has_content

logger = logging.getLogger(__name__)

_NAMESPACE = "FlowingSpeechSynthesizer"
_DEFAULT_VOICE = "longxiaochun"
_DEFAULT_SAMPLE_RATE = 24000
_TOKEN_URL = "https://nls-meta.cn-shanghai.aliyuncs.com/"
_TOKEN_EXPIRE_MARGIN_S = 60.0


def percent_encode(value: str) -> str:
    """阿里云 RPC 签名 percentEncode：A-Za-z0-9-_.~ 不编码，空格→%20。"""
    return quote(value, safe="-_.~")


def build_create_token_url(access_key_id: str, access_key_secret: str) -> str:
    """构造 CreateToken 签名请求 URL（纯函数，便于单测）。"""
    params = {
        "AccessKeyId": access_key_id,
        "Action": "CreateToken",
        "Format": "JSON",
        "RegionId": "cn-shanghai",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "Timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2019-02-28",
    }
    canonical = "&".join(
        f"{percent_encode(k)}={percent_encode(v)}" for k, v in sorted(params.items())
    )
    string_to_sign = "GET&%2F&" + percent_encode(canonical)
    signature = base64.b64encode(
        hmac.new(
            (access_key_secret + "&").encode(),
            string_to_sign.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    return f"{_TOKEN_URL}?{canonical}&Signature={percent_encode(signature)}"


def build_synthesis_message(
    name: str, appkey: str, task_id: str, payload: dict
) -> str:
    """构造 FlowingSpeechSynthesizer 指令消息（StartSynthesis/StopSynthesis）。"""
    return json.dumps(
        {
            "header": {
                "message_id": uuid.uuid4().hex,
                "task_id": task_id,
                "namespace": _NAMESPACE,
                "name": name,
                "appkey": appkey,
            },
            "payload": payload,
        }
    )


class AliyunStreamingTTS:
    """阿里云流式语音合成云端实现（async 接口，逐块 yield AudioFrame）。"""

    def __init__(
        self,
        appkey: str,
        token: str = "",
        access_key_id: str = "",
        access_key_secret: str = "",
        voice: str = _DEFAULT_VOICE,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        volume: int = 50,
        region: str = "cn-beijing",
    ) -> None:
        self._appkey = appkey
        self._token = token  # 直配 token（优先，免 AK/SK 签名）
        self._ak = access_key_id
        self._sk = access_key_secret
        self._voice = voice
        self._sample_rate = sample_rate
        self._volume = volume
        self._region = region
        self._token_cache: tuple[str, float] | None = None  # (token, 到期毫秒)

    def load(self) -> None:
        """云端无本地模型：占位满足 Protocol（连接按需建立）。"""

    def _get_token(self) -> str:
        """获取临时 token：直配优先；否则 AK/SK 签名请求（结果缓存）。"""
        if self._token:
            return self._token
        now_ms = time.time() * 1000
        if (
            self._token_cache is not None
            and now_ms < self._token_cache[1] - _TOKEN_EXPIRE_MARGIN_S * 1000
        ):
            return self._token_cache[0]
        if not self._ak or not self._sk:
            raise RuntimeError("阿里 TTS 需要 token 或 access_key_id/secret")
        url = build_create_token_url(self._ak, self._sk)
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data["Token"]["Id"]
        expire_ms = float(data["Token"]["ExpireTime"])
        self._token_cache = (token, expire_ms)
        logger.info("阿里 TTS token 已获取（有效期 %.1f 分钟）", (expire_ms - now_ms) / 60000)
        return token

    async def synthesize(
        self,
        text: str,
        instruct_text: str = "",
        prompt_wav: str = "",
        speed: float = 1.0,
    ) -> AsyncIterator[AudioFrame]:
        """流式合成一段文本（单段 = 一个 WS 连接）。

        云端忽略 instruct_text/prompt_wav（无参考音色模式）；speed 映射
        speech_rate（1.0 → 0）。
        """
        if not text.strip() or not has_content(text):
            return
        import websockets

        token = await asyncio.to_thread(self._get_token)
        url = f"wss://nls-gateway-{self._region}.aliyuncs.com/ws/v1?token={token}"
        speech_rate = int(round((speed - 1.0) * 500))
        async with websockets.connect(url, max_size=2**24) as ws:
            task_id = uuid.uuid4().hex
            await ws.send(
                build_synthesis_message(
                    "StartSynthesis",
                    self._appkey,
                    task_id,
                    {
                        "session_id": uuid.uuid4().hex,
                        "voice": self._voice,
                        "format": "pcm",
                        "sample_rate": self._sample_rate,
                        "volume": self._volume,
                        "speech_rate": speech_rate,
                        "text": text,
                    },
                )
            )
            async for raw in ws:
                if isinstance(raw, bytes):
                    # 二进制帧 = 合成音频（pcm s16le，按帧推流）
                    yield AudioFrame(data=raw, sample_rate=self._sample_rate)
                    continue
                msg = json.loads(raw)
                name = (msg.get("header") or {}).get("name")
                if name == "TaskFailed":
                    status = (msg.get("header") or {}).get("status_text", "unknown")
                    raise RuntimeError(f"阿里 TTS 任务失败: {status}")
                if name == "SynthesisStarted":
                    # 单段：文本已随 Start 全量发出，立即请求收尾
                    await ws.send(
                        build_synthesis_message(
                            "StopSynthesis", self._appkey, task_id, {}
                        )
                    )
                elif name == "SynthesisCompleted":
                    break
