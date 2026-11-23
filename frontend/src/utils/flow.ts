/** 流程图定义 ↔ vue-flow 画布映射与连线规则（WBS 6.3 编辑器纯函数，可单测）。 */

export type FlowNodeType = "opening" | "intent" | "handler" | "end";

export interface IntentConfig {
  name: string;
  keywords: string;
  description: string;
}

export interface FlowNodeDef {
  id: string;
  type: FlowNodeType;
  /** 画布位置（仅编辑器用；引擎/校验忽略） */
  position?: { x: number; y: number };
  data: Record<string, unknown>;
}

export interface FlowEdgeDef {
  id: string;
  from: string;
  to: string;
  /** intent 出边配置；缺省 = 兜底边 */
  intent?: IntentConfig;
}

export interface FlowDefinition {
  nodes: FlowNodeDef[];
  edges: FlowEdgeDef[];
}

/**
 * 画布浅类型（避免 vue-flow 递归泛型 TS2589；结构化兼容 Node/Edge 组件 props）。
 * 不声明 label（vue-flow 的 label 为 string|VNode|Component 联合，双向赋值会冲突；
 * 需要时经 cast 写入运行时属性，画布照常渲染）。
 */
export interface VFNode {
  id: string;
  position: { x: number; y: number };
  type?: string;
  data?: Record<string, unknown>;
}

export interface VFEdge {
  id: string;
  source: string;
  target: string;
  data?: Record<string, unknown> | null;
}

/** 节点类型 → 画布组件名（vue-flow nodeTypes 注册键） */
export const NODE_COMPONENT: Record<FlowNodeType, string> = {
  opening: "opening-node",
  intent: "intent-node",
  handler: "handler-node",
  end: "end-node",
};

/** 节点类型中文名（面板/校验提示用） */
export const NODE_LABEL: Record<FlowNodeType, string> = {
  opening: "开场白",
  intent: "意图识别",
  handler: "处理节点",
  end: "结束语",
};

/** 连线规则：opening→intent、intent→handler/end、handler→intent（end 无出边）。 */
export function canConnect(fromType: FlowNodeType, toType: FlowNodeType): boolean {
  if (fromType === "opening") return toType === "intent";
  if (fromType === "intent") return toType === "handler" || toType === "end";
  if (fromType === "handler") return toType === "intent";
  return false;
}

/** 画布位置默认排布（新建流程时按类型给坐标）。 */
export function defaultPosition(type: FlowNodeType, index: number): { x: number; y: number } {
  const y = index * 160 + 60;
  if (type === "opening") return { x: 40, y: 160 };
  if (type === "intent") return { x: 320, y: 160 };
  if (type === "end") return { x: 640, y: 60 + index * 140 };
  return { x: 640, y: 80 + index * 140 }; // handler
}

/** definition → vue-flow nodes/edges。 */
export function defToVueFlow(def: FlowDefinition): { nodes: VFNode[]; edges: VFEdge[] } {
  return {
    nodes: def.nodes.map((n) => ({
      id: n.id,
      type: NODE_COMPONENT[n.type],
      position: n.position ?? defaultPosition(n.type, 0),
      data: { nodeType: n.type, ...n.data },
    })),
    edges: def.edges.map(
      (e) =>
        ({
          id: e.id,
          source: e.from,
          target: e.to,
          data: { intent: e.intent ?? null },
          label: e.intent?.name ?? "",
        }) as VFEdge,
    ),
  };
}

/** vue-flow nodes/edges → definition（保存草稿/发布用）。 */
export function vueFlowToDef(nodes: VFNode[], edges: VFEdge[]): FlowDefinition {
  return {
    nodes: nodes.map((n) => {
      const { nodeType, ...data } = (n.data ?? {}) as Record<string, unknown>;
      return {
        id: n.id,
        type: nodeType as FlowNodeType,
        position: { x: n.position.x, y: n.position.y },
        data,
      };
    }),
    edges: edges.map((e) => ({
      id: e.id,
      from: e.source,
      to: e.target,
      ...(e.data?.intent ? { intent: e.data.intent as IntentConfig } : {}),
    })),
  };
}
