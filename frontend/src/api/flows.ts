/** 话术流程图 API（WBS 6.3）：草稿/发布/回滚。 */

import type { FlowDefinition } from "../utils/flow";

export interface FlowSummary {
  id: string;
  scene_id: string;
  name: string;
  description: string;
  version: number;
  published_at: string | null;
  has_unpublished_changes: boolean;
  node_count: number;
  edge_count: number;
}

export interface FlowDetail extends FlowSummary {
  draft: FlowDefinition;
  published: FlowDefinition | null;
}

export async function fetchFlows(sceneId: string): Promise<FlowSummary[]> {
  const resp = await fetch(`/api/flows?scene_id=${encodeURIComponent(sceneId)}`);
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as FlowSummary[];
}

export async function createFlow(body: {
  scene_id: string;
  name: string;
  description: string;
}): Promise<FlowSummary> {
  const resp = await fetch("/api/flows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as FlowSummary;
}

export async function fetchFlow(flowId: string): Promise<FlowDetail> {
  const resp = await fetch(`/api/flows/${flowId}`);
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as FlowDetail;
}

export async function saveDraft(
  flowId: string,
  body: { name?: string; description?: string; draft?: FlowDefinition },
): Promise<FlowSummary> {
  const resp = await fetch(`/api/flows/${flowId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as FlowSummary;
}

export interface FlowVersionInfo {
  version: number;
  published_at: string;
  node_count: number;
  edge_count: number;
}

export async function fetchFlowVersions(flowId: string): Promise<FlowVersionInfo[]> {
  const resp = await fetch(`/api/flows/${flowId}/versions`);
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as FlowVersionInfo[];
}

export async function publishFlow(flowId: string): Promise<FlowSummary> {
  const resp = await fetch(`/api/flows/${flowId}/publish`, { method: "POST" });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as FlowSummary;
}

export async function rollbackFlow(flowId: string, version: number): Promise<FlowSummary> {
  const resp = await fetch(`/api/flows/${flowId}/rollback/${version}`, { method: "POST" });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as FlowSummary;
}

async function _detail(resp: Response): Promise<string> {
  const body = await resp.json().catch(() => null);
  const detail: unknown = body?.detail;
  return typeof detail === "string" ? detail : `请求失败（${resp.status}）`;
}
