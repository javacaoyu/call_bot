"""火山引擎豆包语音合成流式 TTS 云端实现（HTTP Chunked 单向流式-V3）。

协议要点（官方《豆包语音》文档 5.1.1.3，2026-11 版）：
- POST https://openspeech.bytedance.com/api/v3/tts/unidirectional；
- 鉴权 headers：X-Api-Key + X-Api-Resource-Id（seed-tts-2.0 等）；
- body：user.uid + req_params{text, speaker,
  audio_params{format: pcm, sample_rate: 24000, speech_rate}}；
- 响应为 HTTP chunked 流，每块一行 JSON：
  {"code": 0, "message": "", "data": "<base64 音频分块>"}；
  结尾事件 data 为 null（可带 sentence 时间戳）。兼容 SSE 的 "data:" 前缀。
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

_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
_DEFAULT_SPEAKER = "zh_female_vv_uranus_bigtts"
_DEFAULT_SAMPLE_RATE = 24000
# speech_rate 语义：1.0 倍速 = 0；[-50, 100] 线性映射（2.0 倍速 = 100）
_SPEECH_RATE_PER_UNIT = 100


class VolcStreamingTTS:
    """火山豆包语音合成流式 TTS（HTTP chunked，逐块 yield AudioFrame）。"""

    def __init__(
        self,
        api_key: str,
        resource_id: str = "seed-tts-2.0",
        speaker: str = _DEFAULT_SPEAKER,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
    ) -> None:
        self._api_key = api_key
        self._resource_id = resource_id
        self._speaker = speaker
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
        """流式合成一段文本（每段一个 HTTP 流式请求）。

        云端忽略 instruct_text/prompt_wav；speed 线性映射 speech_rate。
        """
        if not text.strip() or not has_content(text):
            return
        body = {
            "user": {"uid": "callbot"},
            "req_params": {
                "text": text,
                "speaker": self._speaker,
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": self._sample_rate,
                    "speech_rate": int(round((speed - 1.0) * _SPEECH_RATE_PER_UNIT)),
                },
            },
        }
        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            async with client.stream("POST", _URL, json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):  # SSE 兼容
                        line = line[len("data:") :].strip()
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    code = data.get("code")
                    if code not in (0, 20000000):
                        raise RuntimeError(f"火山 TTS 错误 {code}: {data.get('message')}")
                    audio_b64 = data.get("data")
                    if audio_b64:
                        yield AudioFrame(
                            data=base64.b64decode(audio_b64),
                            sample_rate=self._sample_rate,
                        )
