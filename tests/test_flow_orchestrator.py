"""流程编排层单元测试（WBS 6.3；Simple 实现 + fake LLM，不依赖 AgentScope/网络）。"""

from callbot.orchestration.flow_orchestrator import SimpleFlowOrchestrator


class _FakeLLM:
    """记录每次请求的 messages，按内容吐固定 token。"""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def generate(self, messages: list[dict]):  # noqa: ANN202
        self.calls.append(messages)
        # 从 system prompt 里提取角色标记（测试用）生成 token
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        yield f"<{system[:6]}>"
        yield "回复"


def _make_orch() -> tuple[SimpleFlowOrchestrator, _FakeLLM]:
    """构造 Simple 编排层 + fake LLM；resolve_prompt 返回节点名标记。"""
    orch = SimpleFlowOrchestrator(
        base_url="http://fake",
        api_key="k",
        model="m",
        resolve_prompt=lambda node: f"SP:{node['id']}",
    )
    fake = _FakeLLM()
    orch._llm = fake  # 注入 fake LLM
    return orch, fake


_NODE_A = {"id": "na", "type": "handler", "data": {"name": "A"}}
_NODE_B = {"id": "nb", "type": "handler", "data": {"name": "B"}}


async def test_per_node_system_prompt() -> None:
    """不同节点 → 不同 system prompt（稳定前缀）。"""
    orch, fake = _make_orch()
    out: list[str] = []
    async for token in orch.stream_handler_reply(_NODE_A, "你好"):
        out.append(token)
    async for token in orch.stream_handler_reply(_NODE_B, "你好"):
        out.append(token)
    assert "<SP:na>" in out and "<SP:nb>" in out
    systems = {calls[0]["content"] for calls in fake.calls}
    assert systems == {"SP:na", "SP:nb"}


async def test_shared_history_across_nodes() -> None:
    """共享历史：B 节点的请求能看到 A 节点的完整对话。"""
    orch, fake = _make_orch()
    async for _ in orch.stream_handler_reply(_NODE_A, "客户第一句"):
        pass
    async for _ in orch.stream_handler_reply(_NODE_B, "客户第二句"):
        pass
    b_call = fake.calls[1]
    contents = [m["content"] for m in b_call if m["role"] in ("user", "assistant")]
    # A 轮问答对（assistant = fake LLM 全部 token 拼接）+ 本轮输入
    assert contents == ["客户第一句", "<SP:na>回复", "客户第二句"]


async def test_spoken_prefix_injected_as_assistant() -> None:
    """打断轮 spoken_prefix 以 assistant 身份入共享历史。"""
    orch, fake = _make_orch()
    async for _ in orch.stream_handler_reply(_NODE_A, "第一句"):
        pass
    async for _ in orch.stream_handler_reply(_NODE_B, "打断后的新句", spoken_prefix="已说的半句"):
        pass
    b_call = fake.calls[1]
    roles = [(m["role"], m["content"]) for m in b_call if m["role"] != "system"]
    assert ("assistant", "已说的半句") in roles


async def test_stream_opening_uses_persona_prompt() -> None:
    """开场 LLM 兜底：使用人设 prompt 的独立 builder。"""
    orch, fake = _make_orch()
    out: list[str] = []
    async for token in orch.stream_opening("（通话开始）", "SP:persona"):
        out.append(token)
    assert out[0] == "<SP:per>"  # 前缀标记来自人设 prompt（取前 6 字符）
    systems = {calls[0]["content"] for calls in fake.calls}
    assert systems == {"SP:persona"}


async def test_simple_warns_tools_but_replies() -> None:
    """Simple 模式绑定工具 → 告警但正常回复（6.4 补执行）。"""
    orch, _ = _make_orch()
    node_with_tools = {
        "id": "nt",
        "type": "handler",
        "data": {"name": "T", "tool_ids": ["x"]},
    }
    out: list[str] = []
    async for token in orch.stream_handler_reply(node_with_tools, "查一下订单"):
        out.append(token)
    assert out  # 回复不受影响
