"""代码插件加载器（WBS 6.3）：启动扫描 plugins/ 目录并注册。

插件四要素约定（docs/工具插件规范.md）：模块暴露
TOOL_NAME / TOOL_DESCRIPTION / Params（ParamsBase 子类）/ async run(params) -> str。
缺要素 → 警告并跳过，不阻断启动。修改插件需重启后端生效。
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentscope.tool import ParamsBase

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path(__file__).parent / "plugins"


@dataclass(frozen=True)
class PluginTool:
    """已加载的代码插件（注册表条目）。"""

    name: str
    description: str
    params_cls: type[ParamsBase]
    run: Callable[..., Awaitable[str]]


_registry: dict[str, PluginTool] = {}


def load_plugins(directory: Path = PLUGINS_DIR) -> int:
    """扫描目录加载全部插件，返回成功数（重复名覆盖旧条目）。"""
    loaded = 0
    if not directory.is_dir():
        logger.warning("插件目录不存在: %s", directory)
        return 0
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            tool = _load_one(path)
        except Exception:  # noqa: BLE001 - 单个插件失败不阻断启动
            logger.exception("插件加载失败，跳过: %s", path.name)
            continue
        if tool is None:
            continue  # 缺要素，已记警告
        _registry[tool.name] = tool
        loaded += 1
        logger.info("插件已注册: %s（参数 %d 个）", tool.name, len(tool.params_cls.model_fields))
    return loaded


def _load_one(path: Path) -> PluginTool | None:
    """加载单个插件模块并校验四要素；不合法返回 None。"""
    spec = importlib.util.spec_from_file_location(f"callbot_tool_{path.stem}", path)
    if spec is None or spec.loader is None:
        logger.warning("插件无法解析: %s", path.name)
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    name = getattr(module, "TOOL_NAME", None)
    description = getattr(module, "TOOL_DESCRIPTION", None)
    params_cls = getattr(module, "Params", None)
    run = getattr(module, "run", None)
    missing = [
        k
        for k, v in {
            "TOOL_NAME": name,
            "TOOL_DESCRIPTION": description,
            "Params": params_cls,
            "run": run,
        }.items()
        if v is None
    ]
    if missing:
        logger.warning("插件 %s 缺少要素，跳过: %s", path.name, "、".join(missing))
        return None
    if not isinstance(name, str) or not name.strip():
        logger.warning("插件 %s 的 TOOL_NAME 非法", path.name)
        return None
    if not isinstance(description, str):
        logger.warning("插件 %s 的 TOOL_DESCRIPTION 必须是字符串", path.name)
        return None
    if not (inspect.isclass(params_cls) and issubclass(params_cls, ParamsBase)):
        logger.warning("插件 %s 的 Params 必须是 ParamsBase 子类", path.name)
        return None
    if not inspect.iscoroutinefunction(run):
        logger.warning("插件 %s 的 run 必须是 async 函数", path.name)
        return None
    # ⚠️ AgentScope 以 **kwargs 调用：run 形参必须覆盖 Params 字段（或收 **kwargs）
    sig_params = inspect.signature(run).parameters
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig_params.values())
    missing_fields = set(params_cls.model_fields) - set(sig_params)
    if not accepts_kwargs and missing_fields:
        logger.warning(
            "插件 %s 的 run 形参未覆盖 Params 字段（AgentScope 以 kwargs 调用），跳过: %s",
            path.name,
            "、".join(sorted(missing_fields)),
        )
        return None
    return PluginTool(name=name.strip(), description=description, params_cls=params_cls, run=run)


def list_plugins() -> list[dict[str, Any]]:
    """已加载插件清单（WebUI「从插件导入」数据源）。"""
    out = []
    for tool in sorted(_registry.values(), key=lambda t: t.name):
        schema = tool.params_cls.model_json_schema()
        props = schema.get("properties", {})
        out.append(
            {
                "name": tool.name,
                "description": tool.description,
                "params": [
                    {
                        "name": key,
                        "type": str(val.get("type", "")),
                        "description": val.get("description", ""),
                    }
                    for key, val in props.items()
                ],
            }
        )
    return out


def get_plugin(name: str) -> PluginTool | None:
    """按名取已加载插件。"""
    return _registry.get(name)
