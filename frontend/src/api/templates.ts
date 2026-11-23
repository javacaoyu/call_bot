/** 行业模板库 API（WBS 6.5）：模板列表 + 一键实例化。 */

export interface TemplateSummary {
  key: string;
  industry: string;
  name: string;
  description: string;
  persona_name: string;
  node_count: number;
  handler_count: number;
  intent_count: number;
}

export interface InstantiateResult {
  scene_id: string;
  scene_name: string;
  persona_id: string;
  flow_id: string;
  flow_version: number;
}

export async function fetchTemplates(): Promise<TemplateSummary[]> {
  const resp = await fetch("/api/templates");
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as TemplateSummary[];
}

export async function instantiateTemplate(key: string): Promise<InstantiateResult> {
  const resp = await fetch(`/api/templates/${encodeURIComponent(key)}/instantiate`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as InstantiateResult;
}

async function _detail(resp: Response): Promise<string> {
  const body = await resp.json().catch(() => null);
  const detail: unknown = body?.detail;
  return typeof detail === "string" ? detail : `请求失败（${resp.status}）`;
}
