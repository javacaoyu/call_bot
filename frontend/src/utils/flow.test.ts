/** 流程图映射与连线规则单测（WBS 6.3）。 */

import { describe, expect, it } from "vitest";
import {
  canConnect,
  defToVueFlow,
  vueFlowToDef,
  type FlowDefinition,
} from "./flow";

const DEF: FlowDefinition = {
  nodes: [
    { id: "n1", type: "opening", position: { x: 1, y: 2 }, data: { text: "您好" } },
    { id: "n2", type: "intent", position: { x: 3, y: 4 }, data: {} },
    { id: "n3", type: "handler", position: { x: 5, y: 6 }, data: { name: "主对话", prompt: "", tool_ids: [] } },
    { id: "n4", type: "end", position: { x: 7, y: 8 }, data: { text: "再见" } },
  ],
  edges: [
    { id: "e1", from: "n1", to: "n2" },
    {
      id: "e2",
      from: "n2",
      to: "n4",
      intent: { name: "结束通话", keywords: "再见", description: "挂断" },
    },
    { id: "e3", from: "n2", to: "n3" },
    { id: "e4", from: "n3", to: "n2" },
  ],
};

describe("canConnect", () => {
  it("opening 只能连 intent", () => {
    expect(canConnect("opening", "intent")).toBe(true);
    expect(canConnect("opening", "handler")).toBe(false);
  });
  it("intent 连 handler/end", () => {
    expect(canConnect("intent", "handler")).toBe(true);
    expect(canConnect("intent", "end")).toBe(true);
    expect(canConnect("intent", "opening")).toBe(false);
  });
  it("handler 必须回连 intent", () => {
    expect(canConnect("handler", "intent")).toBe(true);
    expect(canConnect("handler", "end")).toBe(false);
  });
  it("end 无出边", () => {
    expect(canConnect("end", "intent")).toBe(false);
  });
});

describe("definition ↔ vue-flow 映射", () => {
  it("双向转换保持结构（含位置与意图配置）", () => {
    const { nodes, edges } = defToVueFlow(DEF);
    expect(nodes).toHaveLength(4);
    expect(nodes[0].position).toEqual({ x: 1, y: 2 });
    expect(nodes[0].type).toBe("opening-node");
    const intent = edges[1].data?.intent as { name: string } | null | undefined;
    expect(intent?.name).toBe("结束通话");
    const back = vueFlowToDef(nodes, edges);
    expect(back).toEqual(DEF);
  });

  it("兜底边（无 intent）往返后仍无 intent", () => {
    const { nodes, edges } = defToVueFlow(DEF);
    const fallback = edges[2];
    expect(fallback.data?.intent).toBeNull();
    const back = vueFlowToDef(nodes, edges);
    expect(back.edges[2].intent).toBeUndefined();
  });

  it("无 position 的节点用默认坐标", () => {
    const def = {
      nodes: [{ id: "n1", type: "opening" as const, data: {} }],
      edges: [],
    };
    const { nodes } = defToVueFlow(def);
    expect(nodes[0].position).toEqual({ x: 40, y: 160 });
  });
});
