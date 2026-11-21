"""Provider 配置 API（WBS 4.4）：Web 面板读写三环节走线配置。

GET 返回当前生效配置（json 覆盖层 + env 合并后的 Settings 快照）；
PUT 保存到 provider_config.json 并使模型单例失效（下一路会话即用新走线）。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from callbot.channel.webrtc import invalidate_shared_providers
from callbot.config import Settings
from callbot.providers.config_store import (
    _PROVIDER_FIELDS,
    apply_provider_overrides,
    save_provider_overrides,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["provider_config"])


def _settings_snapshot() -> dict[str, str]:
    """当前生效配置快照（json 覆盖层 > env > 默认）。"""
    settings = Settings()
    apply_provider_overrides(settings)
    return {field: str(getattr(settings, field)) for field in _PROVIDER_FIELDS}


@router.get("/provider_config")
async def get_provider_config() -> dict[str, str]:
    """返回当前生效的三环节配置。"""
    return _settings_snapshot()


@router.put("/provider_config")
async def put_provider_config(payload: dict[str, Any]) -> dict[str, str]:
    """保存配置覆盖层并失效模型单例（热切换：下路会话生效）。

    仅接受白名单字段；非法字段 422；保存失败 500。
    """
    values: dict[str, str] = {}
    for key, value in payload.items():
        if key not in _PROVIDER_FIELDS:
            raise HTTPException(status_code=422, detail=f"未知配置项: {key}")
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"{key} 必须是字符串")
        values[key] = value
    try:
        save_provider_overrides(values)
    except OSError:
        logger.exception("provider_config.json 写入失败")
        raise HTTPException(status_code=500, detail="配置保存失败，请检查磁盘权限") from None
    invalidate_shared_providers()
    logger.info("Provider 配置已更新并失效单例: %s", sorted(values))
    return _settings_snapshot()
