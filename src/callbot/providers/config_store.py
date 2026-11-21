"""Provider 配置存储（WBS 4.4）：Web 面板可写的 JSON 覆盖层。

优先级：provider_config.json（Web 面板保存）> 环境变量/.env > 默认值。
文件不存在时视为空覆盖（全部走 env/默认），保存时创建。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 项目根（相对路径基于项目根解析，避免 cwd 漂移）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _PROJECT_ROOT / "provider_config.json"

# Web 可配置的 provider 相关字段（与 Settings 字段名一一对应）
_PROVIDER_FIELDS = (
    "asr_kind",
    "asr_api_key",
    "asr_resource_id",
    "tts_kind",
    "tts_appkey",
    "tts_token",
    "tts_access_key_id",
    "tts_access_key_secret",
    "tts_voice",
    "tts_volc_speaker",
    "tts_qwen_voice",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
)


def load_provider_overrides(path: Path | None = None) -> dict[str, str]:
    """读 JSON 覆盖层；文件缺失/损坏返回空 dict（不阻断启动）。"""
    target = path or _CONFIG_PATH
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        logger.exception("provider_config.json 解析失败，忽略覆盖层")
        return {}
    return {k: str(v) for k, v in data.items() if k in _PROVIDER_FIELDS}


def save_provider_overrides(values: dict[str, str], path: Path | None = None) -> None:
    """保存 JSON 覆盖层（仅接受白名单字段）。"""
    target = path or _CONFIG_PATH
    filtered = {k: values[k] for k in _PROVIDER_FIELDS if k in values}
    target.write_text(json.dumps(filtered, ensure_ascii=False, indent=2) + "\n")


def apply_provider_overrides(settings: object) -> None:
    """把 JSON 覆盖层应用到 Settings 实例（json > env > 默认）。"""
    for key, value in load_provider_overrides().items():
        setattr(settings, key, value)
