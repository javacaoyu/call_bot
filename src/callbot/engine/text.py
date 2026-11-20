"""文本工具（joiner 与 tts 共用，避免循环导入）。"""

from __future__ import annotations

import re

_CONTENT_RE = re.compile(r"[0-9A-Za-z一-鿿]")


def has_content(text: str) -> bool:
    """是否含数字/字母/汉字（纯标点符号段为 False）。"""
    return bool(_CONTENT_RE.search(text))
