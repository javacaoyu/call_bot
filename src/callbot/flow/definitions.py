"""流程图定义 schema 与结构校验（WBS 6.3）。

画布定义 JSON（draft 与 published 同构，编辑器与引擎共用）：

{
  "nodes": [
    {"id": "n1", "type": "opening", "data": {"text": ""}},
    {"id": "n2", "type": "intent", "data": {}},
    {"id": "n3", "type": "handler", "data": {"name": "主对话", "prompt": "",
        "agent_type": "dialog", "tool_ids": [], "sticky": false}},
    {"id": "n4", "type": "end", "data": {"text": "感谢您的接听，再见。"}}
  ],
  "edges": [
    {"id": "e1", "from": "n1", "to": "n2"},
    {"id": "e2", "from": "n2", "to": "n4",
     "intent": {"name": "结束通话", "keywords": "再见,挂断", "description": "客户要挂断"}},
    {"id": "e3", "from": "n2", "to": "n3"},
    {"id": "e4", "from": "n3", "to": "n2"}
  ]
}

语义：开场白 → 意图识别（每轮必经枢纽）→ handler（AgentScope 智能体）→
回连意图识别循环；结束意图 → 结束语 → 挂断。意图配置在「意图出边」上，
不带 intent 的出边 = 兜底边（至多一条）。
"""

from __future__ import annotations

from typing import Any

NODE_TYPES = ("opening", "intent", "handler", "end")
HANDLER_AGENT_TYPES = ("dialog", "tool")


def build_default_flow() -> dict[str, Any]:
    """默认外呼流程定义：开场白(空=6.2 双轨) → 意图 → 主对话 → 结束语。"""
    return {
        "nodes": [
            {"id": "n_open", "type": "opening", "data": {"text": ""}},
            {"id": "n_intent", "type": "intent", "data": {}},
            {
                "id": "n_main",
                "type": "handler",
                "data": {
                    "name": "主对话",
                    "prompt": "",
                    "agent_type": "dialog",
                    "tool_ids": [],
                    "sticky": False,
                },
            },
            {"id": "n_end", "type": "end", "data": {"text": "感谢您的接听，再见。"}},
        ],
        "edges": [
            {"id": "e1", "from": "n_open", "to": "n_intent"},
            {
                "id": "e2",
                "from": "n_intent",
                "to": "n_end",
                "intent": {
                    "name": "结束通话",
                    "keywords": "再见,不用了,挂断,就这样吧,拜拜",
                    "description": "客户表示要结束通话",
                },
            },
            {"id": "e3", "from": "n_intent", "to": "n_main"},
            {"id": "e4", "from": "n_main", "to": "n_intent"},
        ],
    }


def intent_configs_from(definition: Any) -> list[dict[str, str]]:
    """提取 intent 节点出边的意图配置（分类器 prompt/关键词数据源）。"""
    intents: list[dict[str, str]] = []
    nodes = definition.get("nodes", []) if isinstance(definition, dict) else []
    intent_nodes = [n for n in nodes if n.get("type") == "intent"]
    if not intent_nodes:
        return intents
    intent_id = intent_nodes[0]["id"]
    for e in definition.get("edges", []):
        if e.get("from") != intent_id:
            continue
        cfg = e.get("intent")
        if isinstance(cfg, dict):
            intents.append(
                {
                    "name": str(cfg.get("name", "")),
                    "keywords": str(cfg.get("keywords", "")),
                    "description": str(cfg.get("description", "")),
                }
            )
    return intents


def validate_flow_definition(definition: Any) -> list[str]:
    """校验画布定义结构，返回错误列表（空 = 合法）。

    规则：节点/边 id 唯一；opening/intent 恰一个；handler/end 至少一个；
    边端点存在；opening 无入边且恰一出边；end 无出边；intent 出边带意图
    （兜底边至多一条，意图名唯一）；handler 出边回连 intent；opening 可达全图。
    """
    errors: list[str] = []
    if not isinstance(definition, dict):
        return ["定义必须是 JSON 对象"]
    nodes = definition.get("nodes")
    edges = definition.get("edges")
    if not isinstance(nodes, list) or not nodes:
        return ["必须包含节点列表"]
    if not isinstance(edges, list):
        return ["必须包含边列表"]

    node_map: dict[str, dict] = {}
    for n in nodes:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not n["id"]:
            errors.append("节点缺少合法 id")
            continue
        if n["id"] in node_map:
            errors.append(f"节点 id 重复: {n['id']}")
            continue
        node_map[n["id"]] = n
    if errors:
        return errors  # id 层面已坏，继续无意义

    def of_type(t: str) -> list[dict]:
        return [n for n in nodes if n.get("type") == t]

    openings, intents = of_type("opening"), of_type("intent")
    handlers, ends = of_type("handler"), of_type("end")
    if len(openings) != 1:
        errors.append(f"必须恰好一个 opening 节点（当前 {len(openings)}）")
    if len(intents) != 1:
        errors.append(f"必须恰好一个 intent 节点（当前 {len(intents)}）")
    if not handlers:
        errors.append("至少需要一个 handler 节点")
    if not ends:
        errors.append("至少需要一个 end 节点")
    for n in nodes:
        if n.get("type") not in NODE_TYPES:
            errors.append(f"未知节点类型: {n['type']}")
    if errors:
        return errors

    edge_ids: set[str] = set()
    for e in edges:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e["id"]:
            errors.append("边缺少合法 id")
            continue
        if e["id"] in edge_ids:
            errors.append(f"边 id 重复: {e['id']}")
        edge_ids.add(e["id"])
        for endpoint in ("from", "to"):
            if e.get(endpoint) not in node_map:
                errors.append(f"边 {e['id']} 端点不存在: {e[endpoint]}")
    # 端点非法的边已报告，后续结构规则只处理端点完整的边
    valid_edges = [
        e for e in edges if e.get("from") in node_map and e.get("to") in node_map
    ]

    intent_node = intents[0]
    in_degree = {nid: 0 for nid in node_map}
    for e in valid_edges:
        in_degree[e["to"]] += 1

    # opening：无入边，恰一条出边
    open_id = openings[0]["id"]
    if in_degree[open_id] != 0:
        errors.append("opening 节点不允许有入边")
    open_out = [e for e in valid_edges if e["from"] == open_id]
    if len(open_out) != 1:
        errors.append(f"opening 节点必须恰好一条出边（当前 {len(open_out)}）")

    # end：无出边
    for end in ends:
        if any(e["from"] == end["id"] for e in valid_edges):
            errors.append(f"end 节点不允许有出边: {end['id']}")

    # intent：出边带意图；兜底边至多一条；意图名唯一；目标限 handler/end
    intent_out = [e for e in valid_edges if e["from"] == intent_node["id"]]
    if not intent_out:
        errors.append("intent 节点至少需要一条出边")
    intent_names: set[str] = set()
    fallback_count = 0
    for e in intent_out:
        target = node_map[e["to"]]["type"]
        if target not in ("handler", "end"):
            errors.append(f"intent 出边只能连 handler 或 end: {e['id']}")
        cfg = e.get("intent")
        if cfg is None:
            fallback_count += 1
            continue
        if not isinstance(cfg, dict) or not str(cfg.get("name", "")).strip():
            errors.append(f"意图边缺少意图名: {e['id']}")
            continue
        name = str(cfg["name"]).strip()
        if name in intent_names:
            errors.append(f"意图名重复: {name}")
        intent_names.add(name)
        if not isinstance(cfg.get("keywords", ""), str) or not isinstance(
            cfg.get("description", ""), str
        ):
            errors.append(f"意图 {name} 的关键词/描述必须是字符串")
    if fallback_count > 1:
        errors.append(f"intent 兜底边（无意图）至多一条（当前 {fallback_count}）")

    # handler：至少一条出边且必须回连 intent
    for h in handlers:
        h_out = [e for e in valid_edges if e["from"] == h["id"]]
        if not h_out:
            errors.append(f"handler 节点缺少出边（需回连 intent）: {h['id']}")
        for e in h_out:
            if e["to"] != intent_node["id"]:
                errors.append(f"handler 出边必须回连 intent 节点: {e['id']}")

    # handler data 校验
    for h in handlers:
        data = h.get("data") or {}
        if not isinstance(data.get("prompt", ""), str):
            errors.append(f"handler {h['id']} 的 prompt 必须是字符串")
        if data.get("agent_type", "dialog") not in HANDLER_AGENT_TYPES:
            errors.append(f"handler {h['id']} 的 agent_type 非法")
        tool_ids = data.get("tool_ids", [])
        if not isinstance(tool_ids, list) or not all(
            isinstance(t, str) for t in tool_ids
        ):
            errors.append(f"handler {h['id']} 的 tool_ids 必须是字符串列表")

    # 连通性：opening 出发 BFS 可达全部节点
    adj: dict[str, list[str]] = {nid: [] for nid in node_map}
    for e in valid_edges:
        adj[e["from"]].append(e["to"])
    seen: set[str] = set()
    stack = [open_id]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj[cur])
    unreachable = set(node_map) - seen
    if unreachable:
        errors.append(f"存在不可达节点: {', '.join(sorted(unreachable))}")

    return errors
