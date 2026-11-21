"""千问平台（通义 DashScope）语音合成流式 TTS 云端实现（HTTP SSE）。

协议要点（官方文档 api-reference/speech-synthesis/qwen-audio-tts/http-api）：
- POST https://maas.qianwenaiapi.com/api/v1/services/audio/tts/SpeechSynthesizer；
- 鉴权 Authorization: Bearer $KEY；流式需 X-DashScope-SSE: enable；
- body：model（qwen-audio-3.1-tts-flash）+ input{text, voice, format: pcm,
  sample_rate, rate（语速 0.5-2.0）}；
- SSE 分块：output.audio.data 为 base64 音频数据（逐块 yield）。
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncIterator

import httpx

from callbot.engine.frames import AudioFrame
from callbot.engine.text import has_content

logger = logging.getLogger(__name__)

_URL = "https://maas.qianwenaiapi.com/api/v1/services/audio/tts/SpeechSynthesizer"
_DEFAULT_MODEL = "qwen-audio-3.1-tts-flash"
_DEFAULT_VOICE = "longanhuan_v3.1"
_DEFAULT_SAMPLE_RATE = 24000


class QwenStreamingTTS:
    """千问语音合成流式 TTS（HTTP SSE，逐块 yield AudioFrame）。"""

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        voice: str = _DEFAULT_VOICE,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._sample_rate = sample_rate

    def load(self) -> None:
        """云端无本地模型：占位满足 Protocol（请求按需发起）。"""

    async def synthesize(
        self,
        text: str,
        instruct_text: str = "",
        prompt_wav: str = "",
        speed: float = 1.0,
    ) -> AsyncIterator[AudioFrame]:
        """流式合成一段文本（每段一个 HTTP SSE 请求）。

        云端忽略 instruct_text/prompt_wav；speed 直接映射 input.rate（1.0 倍速）。
        """
        if not text.strip() or not has_content(text):
            return
        body = {
            "model": self._model,
            "input": {
                "text": text,
                "voice": self._voice,
                "format": "pcm",
                "sample_rate": self._sample_rate,
                "rate": speed,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            async with client.stream("POST", _URL, json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[len("data:") :].strip()
                    if line.startswith("event:") or line.startswith("id:"):
                        continue  # SSE 控制行
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("code") and data["code"] != 0:
                        raise RuntimeError(
                            f"千问 TTS 错误 {data.get('code')}: {data.get('message')}"
                        )
                    audio_b64 = ((data.get("output") or {}).get("audio") or {}).get("data")
                    if audio_b64:
                        yield AudioFrame(
                            data=base64.b64decode(audio_b64),
                            sample_rate=self._sample_rate,
                        )
