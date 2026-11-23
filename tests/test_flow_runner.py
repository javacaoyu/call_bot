"""意图中枢引擎单元测试（WBS 6.3；纯逻辑，fake 注入不依赖 LLM）。"""

from typing import Any

from callbot.flow.intent import IntentClassifier
from callbot.flow.runner import FlowRunner, FlowState

# ---------- 构造工具 ----------


def _flow(
    *,
    opening_text: str = "",
    intents: list[dict] | None = None,
    fallback: str | None = "n_main",
    handlers: list[dict] | None = None,
    end_text: str = "感谢您的接听，再见。",
) -> dict[str, Any]:
    """构造测试流程：开场白 → intent（可配意图边/兜底）→ handler 回连 → end。"""
    handlers = handlers or [{"id": "n_main", "name": "主对话"}]
    nodes = [
        {"id": "n_open", "type": "opening", "data": {"text": opening_text}},
        {"id": "n_intent", "type": "intent", "data": {}},
    ]
    for h in handlers:
        nodes.append(
            {
                "id": h["id"],
                "type": "handler",
                "data": {
                    "name": h["name"],
                    "prompt": "",
                    "agent_type": "dialog",
                    "tool_ids": [],
                    "sticky": bool(h.get("sticky", False)),
                },
            }
        )
    nodes.append({"id": "n_end", "type": "end", "data": {"text": end_text}})
    edges = [{"id": "e_open", "from": "n_open", "to": "n_intent"}]
    for i, it in enumerate(intents or []):
        edges.append(
            {
                "id": f"e_int{i}",
                "from": "n_intent",
                "to": it["target"],
                "intent": {
                    "name": it["name"],
                    "keywords": it.get("keywords", ""),
                    "description": it.get("description", ""),
                },
            }
        )
    if fallback:
        edges.append({"id": "e_fb", "from": "n_intent", "to": fallback})
    for h in handlers:
        edges.append({"id": f"e_back_{h['id']}", "from": h["id"], "to": "n_intent"})
    return {"nodes": nodes, "edges": edges}


async def _collect(agen) -> str:  # noqa: ANN001
    """收集异步生成器的全部 token。"""
    pieces: list[str] = []
    async for token in agen:
        pieces.append(token)
    return "".join(pieces)


def _fake_reply(marker: str = ""):
    """fake handler 回复流：带节点名标记，便于断言路由去向。"""

    async def reply(node: dict, text: str, spoken_prefix: str | None = None):  # noqa: ANN202
        name = (node.get("data") or {}).get("name", node["id"])
        yield f"[{marker}{name}]:{text}"

    return reply


# ---------- 开场白 ----------


async def test_start_direct_opening() -> None:
    """opening 节点文本直读；不调 open_stream。"""
    called = False

    async def open_stream():  # noqa: ANN202
        nonlocal called
        called = True
        yield "不该出现"

    runner = FlowRunner(_flow(opening_text="您好"), open_stream=open_stream)
    assert runner.state is FlowState.INIT
    assert await _collect(runner.start()) == "您好"
    assert runner.state is FlowState.AWAITING
    assert called is False


async def test_start_open_stream_fallback() -> None:
    """opening 空文本 → open_stream 兜底（6.2 双轨语义）。"""

    async def open_stream():  # noqa: ANN202
        yield "您好，"
        yield "请问是陈女士吗？"

    runner = FlowRunner(_flow(opening_text=""), open_stream=open_stream)
    assert await _collect(runner.start()) == "您好，请问是陈女士吗？"


# ---------- 路由与循环 ----------


async def test_keyword_routing() -> None:
    """关键词快路径路由到对应 handler。"""
    runner = FlowRunner(
        _flow(
            intents=[{"name": "投诉", "keywords": "投诉,差评", "target": "n_complain"}],
            handlers=[{"id": "n_main", "name": "主对话"}, {"id": "n_complain", "name": "投诉处理"}],
        ),
        reply=_fake_reply(),
    )
    await _collect(runner.start())
    out = await _collect(runner.on_user_text("我要投诉你们"))
    assert out == "[投诉处理]:我要投诉你们"
    assert runner.state is FlowState.AWAITING


async def test_llm_classify_routing() -> None:
    """关键词未命中 → LLM 分类路由。"""
    calls: list[str] = []

    async def classify_fn(text: str) -> str | None:
        calls.append(text)
        return "投诉" if "不满" in text else None

    runner = FlowRunner(
        _flow(
            intents=[{"name": "投诉", "keywords": "投诉", "target": "n_complain"}],
            handlers=[{"id": "n_main", "name": "主对话"}, {"id": "n_complain", "name": "投诉处理"}],
        ),
        reply=_fake_reply(),
        classify_fn=classify_fn,
    )
    await _collect(runner.start())
    out = await _collect(runner.on_user_text("我对你们很不满"))
    assert out == "[投诉处理]:我对你们很不满"
    assert calls == ["我对你们很不满"]


async def test_fallback_routing() -> None:
    """分类未命中 → 兜底边。"""

    async def classify_fn(text: str) -> str | None:  # noqa: ARG001
        return None

    runner = FlowRunner(
        _flow(handlers=[{"id": "n_main", "name": "主对话"}]),
        reply=_fake_reply(),
        classify_fn=classify_fn,
    )
    await _collect(runner.start())
    assert await _collect(runner.on_user_text("随便聊聊")) == "[主对话]:随便聊聊"


async def test_no_fallback_silent() -> None:
    """无兜底边 + 分类未命中 → 不回复，回 awaiting。"""

    async def classify_fn(text: str) -> str | None:  # noqa: ARG001
        return None

    runner = FlowRunner(
        _flow(fallback=None, handlers=[{"id": "n_main", "name": "主对话"}]),
        reply=_fake_reply(),
        classify_fn=classify_fn,
    )
    await _collect(runner.start())
    assert await _collect(runner.on_user_text("听不懂的话")) == ""
    assert runner.state is FlowState.AWAITING


async def test_end_intent() -> None:
    """结束意图 → 结束语 + on_end → ended 后输入忽略。"""
    on_end_calls: list[str] = []

    async def on_end(text: str) -> None:
        on_end_calls.append(text)

    runner = FlowRunner(
        _flow(
            intents=[
                {"name": "结束通话", "keywords": "再见,挂断", "target": "n_end"},
            ],
            handlers=[{"id": "n_main", "name": "主对话"}],
        ),
        reply=_fake_reply(),
        on_end=on_end,
    )
    await _collect(runner.start())
    out = await _collect(runner.on_user_text("好的再见"))
    assert out == "感谢您的接听，再见。"
    assert on_end_calls == ["感谢您的接听，再见。"]
    assert runner.state is FlowState.ENDED
    # ended 后输入忽略
    assert await _collect(runner.on_user_text("我还有问题")) == ""


async def test_sticky_handler() -> None:
    """吸附模式：未命中关键词的轮次跳过 LLM 分类留在本 handler。"""
    classify_calls = 0

    async def classify_fn(text: str) -> str | None:  # noqa: ANN202
        nonlocal classify_calls
        classify_calls += 1
        return None

    runner = FlowRunner(
        _flow(
            intents=[
                {"name": "投诉", "keywords": "投诉", "target": "n_complain"},
            ],
            handlers=[
                {"id": "n_main", "name": "主对话", "sticky": True},
                {"id": "n_complain", "name": "投诉处理"},
            ],
        ),
        reply=_fake_reply(),
        classify_fn=classify_fn,
    )
    await _collect(runner.start())
    # 第一轮：未命中关键词 → LLM 分类 None → 兜底进主对话
    assert await _collect(runner.on_user_text("你好")) == "[主对话]:你好"
    assert classify_calls == 1
    # 第二轮（吸附中）：无关键词 → 跳过 LLM 分类，留在主对话
    assert await _collect(runner.on_user_text("然后呢")) == "[主对话]:然后呢"
    assert classify_calls == 1  # 分类未再调用
    # 关键词命中 → 离开吸附，路由投诉处理
    assert await _collect(runner.on_user_text("我要投诉")) == "[投诉处理]:我要投诉"


async def test_interrupt_cancel_back_to_awaiting() -> None:
    """打断 = 取消回复流：finally 保证回 awaiting，新转写可投递。"""
    runner = FlowRunner(_flow(handlers=[{"id": "n_main", "name": "主对话"}]),
                        reply=_fake_reply())
    await _collect(runner.start())
    gen = runner.on_user_text("开始说话")
    async for token in gen:
        assert token.startswith("[主对话]")
        break  # 模拟打断
    await gen.aclose()  # 打断语义 = 关闭生成器（生产为 task.cancel → aclose）
    assert runner.state is FlowState.AWAITING
    assert await _collect(runner.on_user_text("继续说")) == "[主对话]:继续说"


async def test_ignore_before_start() -> None:
    """开场前输入忽略。"""
    runner = FlowRunner(_flow(handlers=[{"id": "n_main", "name": "主对话"}]),
                        reply=_fake_reply())
    assert await _collect(runner.on_user_text("提前说话")) == ""
    assert runner.state is FlowState.INIT


async def test_spoken_prefix_passthrough() -> None:
    """打断上下文重建素材（spoken_prefix）透传给 handler 回复回调。"""
    seen: list[str | None] = []

    async def reply(node: dict, text: str, spoken_prefix: str | None = None):  # noqa: ANN202
        seen.append(spoken_prefix)
        yield "[回复]"

    runner = FlowRunner(_flow(handlers=[{"id": "n_main", "name": "主对话"}]),
                        reply=reply)
    await _collect(runner.start())
    assert await _collect(runner.on_user_text("你好")) == "[回复]"
    assert await _collect(runner.on_user_text("继续说", "已说的半句")) == "[回复]"
    assert seen == [None, "已说的半句"]


async def test_interrupt_end_speech_back_to_awaiting() -> None:
    """打断结束语 = 回到 awaiting，可继续对话（结束后不挂断）。"""
    runner = FlowRunner(
        _flow(
            intents=[{"name": "结束通话", "keywords": "再见", "target": "n_end"}],
            handlers=[{"id": "n_main", "name": "主对话"}],
        ),
        reply=_fake_reply(),
    )
    await _collect(runner.start())
    gen = runner.on_user_text("再见")
    async for token in gen:
        assert "感谢" in token
        break  # 打断结束语
    await gen.aclose()
    assert runner.state is FlowState.AWAITING
    assert await _collect(runner.on_user_text("再聊两句")) == "[主对话]:再聊两句"


# ---------- 分类器 ----------


def test_match_keywords_rules() -> None:
    """关键词匹配：顺序优先 / 多关键词 / 空关键词跳过 / 未命中 None。"""
    c = IntentClassifier(
        [
            {"name": "投诉", "keywords": "投诉, 差评", "description": ""},
            {"name": "咨询", "keywords": "怎么, 如何", "description": ""},
            {"name": "结束通话", "keywords": "", "description": ""},
        ]
    )
    assert c.match_keywords("我要投诉") == "投诉"
    assert c.match_keywords("给个差评") == "投诉"
    assert c.match_keywords("这个怎么用") == "咨询"
    assert c.match_keywords("没关键词") is None


async def test_classify_keyword_short_circuit() -> None:
    """快路径命中时不调 LLM。"""
    called = False

    async def classify_fn(text: str) -> str | None:  # noqa: ANN202
        nonlocal called
        called = True
        return None

    c = IntentClassifier([{"name": "投诉", "keywords": "投诉", "description": ""}], classify_fn)
    assert await c.classify("我要投诉") == "投诉"
    assert called is False


async def test_classify_llm_and_normalize() -> None:
    """LLM 分类结果归一：不在列表 → None；异常 → None。"""

    async def ok_fn(text: str) -> str | None:  # noqa: ARG001
        return "投诉"

    async def bad_fn(text: str) -> str | None:  # noqa: ARG001
        return "不存在的意图"

    async def boom_fn(text: str) -> str | None:  # noqa: ARG001
        raise RuntimeError("llm down")

    c = IntentClassifier([{"name": "投诉", "keywords": "投诉", "description": ""}], ok_fn)
    assert await c.classify("没有关键词的句子") == "投诉"
    c_bad = IntentClassifier([{"name": "投诉", "keywords": "投诉", "description": ""}], bad_fn)
    assert await c_bad.classify("x") is None
    c_boom = IntentClassifier([{"name": "投诉", "keywords": "投诉", "description": ""}], boom_fn)
    assert await c_boom.classify("x") is None
