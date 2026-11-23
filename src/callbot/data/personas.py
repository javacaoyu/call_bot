"""激活人设查询与变量插槽渲染（WBS 6.1/6.2）。"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from callbot.config import Settings
from callbot.data.models import Persona, get_engine
from callbot.orchestration.context import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# 内置变量（6.2）：客户变量在外呼那一刻动态注入（模板存原文，不含客户信息）；
# 时间类实时填充
BUILTIN_VARIABLES: dict[str, str] = {
    "客户姓名": "客户",
    "电话号码": "客户手机号",
    "客户备注": "",
    "今天日期": "",
    "当前时间": "",
    "星期几": "",
}

_VAR_PATTERN = re.compile(r"\{([^{}]+)\}")

# 中文星期
_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def builtin_variable_values(now: datetime | None = None) -> dict[str, str]:
    """内置变量的当前值（时间类实时计算；now 注入便于测试）。"""
    moment = now or datetime.now()
    return {
        **BUILTIN_VARIABLES,
        "今天日期": moment.strftime("%Y年%m月%d日"),
        "当前时间": moment.strftime("%H:%M"),
        "星期几": _WEEKDAYS[moment.weekday()],
    }


def extract_variables(template: str) -> set[str]:
    """提取模板中所有 {变量名} 占位符（去重）。"""
    return {m.group(1).strip() for m in _VAR_PATTERN.finditer(template)}


def render_prompt(template: str, context: dict[str, str] | None = None) -> str:
    """渲染变量插槽：context 覆盖内置值；未定义变量原样保留。"""
    values = builtin_variable_values()
    if context:
        values.update(context)
    return _VAR_PATTERN.sub(lambda m: values.get(m.group(1).strip(), m.group(0)), template)


def get_persona_prompt(persona_id: str | None, settings: Settings | None = None) -> str | None:
    """按 id 取人设模板（未渲染）；不存在返回 None。"""
    if persona_id is None:
        return None
    try:
        import uuid

        with Session(get_engine(settings)) as session:
            persona = session.get(Persona, uuid.UUID(persona_id))
            if persona is not None:
                return persona.system_prompt
    except Exception:  # noqa: BLE001
        logger.exception("读取人设失败")
    return None


def render_with_context(
    template: str,
    customer: dict[str, str] | None = None,
) -> str:
    """渲染模板：客户变量填充 + 时间行自动附加（6.2）。

    时间在会话建立时渲染一次（会话内多轮稳定，不破坏 prompt 缓存）；
    客户变量由外呼前选择的客户提供。
    """
    values = builtin_variable_values()
    if customer:
        values["客户姓名"] = customer.get("name", values["客户姓名"])
        values["电话号码"] = customer.get("phone", values["电话号码"])
        values["客户备注"] = customer.get("notes", values["客户备注"])
    rendered = render_prompt(template, values)
    moment = values["今天日期"] + " " + values["星期几"] + " " + values["当前时间"]
    return f"{rendered}\n（当前时间：{moment}）"


def get_active_persona_template(settings: Settings | None = None) -> str | None:
    """当前激活人设的模板（未渲染）；无激活人设返回 None。"""
    try:
        with Session(get_engine(settings)) as session:
            persona = session.scalars(
                select(Persona).where(Persona.is_active).limit(1)
            ).first()
            return persona.system_prompt if persona is not None else None
    except Exception:  # noqa: BLE001 - DB 不可用回退，不阻断对话
        logger.exception("读取激活人设失败")
        return None


def get_active_persona_prompt(settings: Settings | None = None) -> str:
    """当前激活人设渲染后的 system prompt；无则回退默认文案。"""
    template = get_active_persona_template(settings)
    if template is not None:
        return render_with_context(template)
    return DEFAULT_SYSTEM_PROMPT


def get_opening_template(
    persona_id: str | None,
    settings: Settings | None = None,
) -> str | None:
    """按 id 取人设开场白模板（未渲染）；未配置或不存在返回 None。"""
    if persona_id is None:
        return None
    try:
        import uuid

        with Session(get_engine(settings)) as session:
            persona = session.get(Persona, uuid.UUID(persona_id))
            if persona is not None and persona.opening.strip():
                return persona.opening
    except Exception:  # noqa: BLE001
        logger.exception("读取人设开场白失败")
    return None


def get_active_opening_template(settings: Settings | None = None) -> str | None:
    """当前激活人设的开场白模板（未渲染）；未配置返回 None。"""
    try:
        with Session(get_engine(settings)) as session:
            persona = session.scalars(
                select(Persona).where(Persona.is_active).limit(1)
            ).first()
            if persona is not None and persona.opening.strip():
                return persona.opening
    except Exception:  # noqa: BLE001 - DB 不可用回退，不阻断对话
        logger.exception("读取激活人设开场白失败")
        return None
    return None


def render_opening(
    template: str,
    customer: dict[str, str] | None = None,
) -> str:
    """渲染开场白（口播文本）：客户变量 + 时间变量，**不附加时间行**。

    与 system prompt 渲染不同：开场白直接朗读，「（当前时间…）」不可读。
    """
    values = builtin_variable_values()
    if customer:
        values["客户姓名"] = customer.get("name", values["客户姓名"])
        values["电话号码"] = customer.get("phone", values["电话号码"])
        values["客户备注"] = customer.get("notes", values["客户备注"])
    return render_prompt(template, values).strip()


def resolve_opening(
    persona_id: str | None,
    settings: Settings | None = None,
    customer: dict[str, str] | None = None,
) -> str | None:
    """外呼开场白（6.2）：所选人设开场白 → 激活人设 → None。

    模板存原文、客户变量在外呼那一刻动态注入（同一人设外呼不同客户）；
    None 表示未配置，由 LLM 按人设兜底生成。
    **6.3 流程编排接入点**：流程图的起始节点将替换本函数。
    """
    template = get_opening_template(persona_id, settings)
    if template is None:
        template = get_active_opening_template(settings)
    if template is None:
        return None
    return render_opening(template, customer)


def build_handler_system_prompt(
    base: str,
    extra: str,
    customer: dict[str, str] | None = None,
) -> str:
    """组装 handler 节点的 system prompt：基础人设 + 本环节话术要求（**追加非替代**）。

    节点 prompt 若完全替代人设，LLM 只见孤立的指令、无身份背景，
    会自行脑补身份（实测翻车：被当成 AI 服务商推销）。
    追加语义下人设打底 + 节点话术约束，且前缀按节点字节级稳定（缓存友好）。
    """
    if not extra.strip():
        return base
    rendered = render_opening(extra, customer)  # 客户变量注入，不附时间行
    return f"{base}\n\n## 本环节话术要求（必须遵守）\n{rendered}"
