"""演示插件：模拟订单查询（6.3 联调用，固定 mock 数据，后续接真实订单系统时替换）。"""

from __future__ import annotations

from agentscope.tool import ParamsBase
from pydantic import Field

TOOL_NAME = "mock_query_order"
TOOL_DESCRIPTION = "按订单号查询订单状态与金额（演示用 mock 数据），参数 order_id 为订单号"

_MOCK_ORDERS = {
    "20261123001": "已发货，金额 128 元",
    "20261123002": "待支付，金额 4580 元",
    "20261123003": "已完成，金额 99 元",
}


class Params(ParamsBase):
    """参数 schema：自动转 JSON schema 给 LLM 填参。"""

    order_id: str = Field(description="订单号，如 20261123001")


async def run(order_id: str) -> str:
    """执行体：查订单状态，返回自然语言结果（拼进对话上下文）。

    ⚠️ AgentScope 以 **kwargs 调用：形参必须与 Params 字段一一对应。
    """
    status = _MOCK_ORDERS.get(order_id.strip())
    if status is None:
        return f"未查到订单 {order_id}，请确认订单号是否正确"
    return f"订单 {order_id} 状态：{status}"
