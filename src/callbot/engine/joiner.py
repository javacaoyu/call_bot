"""流式衔接器：LLM token 流 → TTS 音频帧流（首 token 即开始累积，句边界触发合成）。

延迟优先（PRD 5.2）：不等 LLM 整句完成，遇句末标点或达到阈值即触发 TTS。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from callbot.engine.frames import AudioFrame
from callbot.providers.tts import StreamingTTS

logger = logging.getLogger(__name__)

_SEGMENT_PUNCT = ("。", "！", "？", "；", "\n")
DEFAULT_MAX_CHARS = 20


def split_segment(buffer: str, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, str]:
    """从缓冲中切出一个可合成段。

    规则：遇到句末标点即切（含标点）；无标点但达到 max_chars 也切；
    否则不切。返回 (段, 剩余)。
    """
    for i, ch in enumerate(buffer):
        if ch in _SEGMENT_PUNCT:
            return buffer[: i + 1], buffer[i + 1 :]
    if len(buffer) >= max_chars:
        return buffer[:max_chars], buffer[max_chars:]
    return "", buffer


class SpeechJoiner:
    """LLM 流 → TTS 流衔接器。

    Usage:
        joiner = SpeechJoiner(tts)
        async for frame in joiner.run(llm_token_stream):
            ...  # 每个合成段的音频帧
    """

    def __init__(self, tts: StreamingTTS, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self._tts = tts
        self._max_chars = max_chars

    async def run(self, tokens: AsyncIterator[str]) -> AsyncIterator[AudioFrame]:
        """消费 LLM token 流，产出 TTS 音频帧流。

        Args:
            tokens: LLM 回复 token 流。

        Yields:
            每个合成段的 AudioFrame。
        """
        buffer = ""
        async for token in tokens:
            buffer += token
            while True:
                segment, rest = split_segment(buffer, self._max_chars)
                if not segment:
                    break
                logger.info("触发合成段: %s", segment)
                async for frame in self._tts.synthesize(segment):
                    yield frame
                buffer = rest
        # 流结束 flush 尾段
        if buffer.strip():
            logger.info("触发合成尾段: %s", buffer)
            async for frame in self._tts.synthesize(buffer):
                yield frame
