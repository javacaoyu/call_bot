"""工具装配（WBS 6.3）：工具表记录 → AgentScope Toolkit。

- plugin：插件 Params（schema）+ 扁平形参 run 包成 FunctionTool
- http：pydantic create_model 动态生成 ParamsBase（schema）+ 通用 HTTP 执行函数

⚠️ AgentScope 2.0.12 以 **kwargs 扁平调用工具函数（实测，传 params 实例会
TypeError）：Params 类只作 JSON schema，run 的形参必须与 Params 字段一一对应。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from pydantic import Field, create_model
from sqlalchemy.orm import Session

from callbot.config import Settings
from callbot.data.models import Tool, get_engine
from callbot.tools.loader import get_plugin

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_S = 5.0
_RESPONSE_MAX_CHARS = 2000

_HTTP_FIELD_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


async def build_toolkit(
    tool_ids: list[str],
    settings: Settings | None = None,
) -> Any | None:
    """按工具 id 装配 AgentScope Toolkit；一个都没装成功返回 None。"""
    from agentscope.permission import PermissionBehavior, PermissionDecision
    from agentscope.tool import Toolkit
    from agentscope.tool._adapters import FunctionTool

    toolkit = Toolkit()
    built = 0
    with Session(get_engine(settings)) as session:
        for tool_id in tool_ids:
            try:
                tool = session.get(Tool, uuid.UUID(tool_id))
            except ValueError:
                tool = None
            if tool is None:
                logger.warning("工具不存在，跳过: %s", tool_id)
                continue
            spec = _build_http(tool) if tool.kind == "http" else _build_plugin(tool)
            if spec is None:
                continue
            name, description, schema_cls, func = spec
            await toolkit.add_tool(
                FunctionTool(
                    func,
                    name=name,
                    description=description,
                    input_schema=schema_cls,
                    permission=PermissionDecision(
                        behavior=PermissionBehavior.ALLOW,
                        message="话术流程内自动放行",
                    ),
                )
            )
            built += 1
    if built == 0:
        return None
    logger.info("工具装配完成: %d/%d 个", built, len(tool_ids))
    return toolkit


def _build_plugin(tool: Tool) -> tuple[str, str, type, Any] | None:
    """代码插件：注册表里取 Params/run 包成 FunctionTool 要素。"""
    plugin_name = str((tool.config or {}).get("plugin", ""))
    plugin = get_plugin(plugin_name)
    if plugin is None:
        logger.warning("插件未加载，跳过工具 %s: %s", tool.name, plugin_name)
        return None
    return tool.name, tool.description, plugin.params_cls, plugin.run


def _build_http(tool: Tool) -> tuple[str, str, type, Any] | None:
    """HTTP 配置工具：动态 ParamsBase + 通用 HTTP 执行函数（含超时）。"""
    config = tool.config or {}
    url = str(config.get("url", ""))
    if not url:
        logger.warning("HTTP 工具缺少 url，跳过: %s", tool.name)
        return None
    method = str(config.get("method", "GET")).upper()
    headers = config.get("headers") or {}
    params_specs = config.get("params") or []

    fields: dict[str, Any] = {}
    for spec in params_specs:
        if not isinstance(spec, dict) or not spec.get("name"):
            continue
        pname = spec["name"]
        ptype = _HTTP_FIELD_TYPES.get(str(spec.get("type", "string")), str)
        default = ... if spec.get("required") else None
        fields[pname] = (
            ptype,
            Field(default=default, description=str(spec.get("description", ""))),
        )
    schema_cls = create_model(
        f"HttpTool_{tool.id.hex[:8]}",
        __base__=__import__("agentscope.tool", fromlist=["ParamsBase"]).ParamsBase,
        **fields,
    )

    async def run(**kwargs: Any) -> str:
        """执行 HTTP 调用：{参数} 占位替换 + GET 查询参 / POST JSON 体。"""
        try:
            target = url.format(**kwargs)
        except (KeyError, ValueError) as exc:
            return f"工具调用失败：URL 占位参数缺失或非法（{exc}）"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
                if method == "POST":
                    resp = await client.post(target, json=kwargs, headers=headers or None)
                else:
                    resp = await client.get(target, params=kwargs, headers=headers or None)
            resp.raise_for_status()
            return resp.text[:_RESPONSE_MAX_CHARS]
        except Exception as exc:  # noqa: BLE001 - 失败信息反馈给 LLM 换策略
            return f"工具调用失败：{type(exc).__name__}: {exc}"

    return tool.name, tool.description, schema_cls, run
