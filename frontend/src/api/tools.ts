/** 工具库 API（WBS 6.3）：HTTP 配置工具 CRUD + 代码插件清单。 */

export interface ToolParamSpec {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

export interface ToolConfig {
  url?: string;
  method?: string;
  headers?: Record<string, string>;
  params?: ToolParamSpec[];
  plugin?: string;
}

export interface Tool {
  id: string;
  scene_id: string | null;
  name: string;
  description: string;
  kind: "http" | "plugin" | "builtin";
  config: ToolConfig;
  builtin: boolean;
  created_at: string;
}

export interface PluginInfo {
  name: string;
  description: string;
  params: ToolParamSpec[];
}

export async function fetchTools(sceneId: string): Promise<Tool[]> {
  const resp = await fetch(`/api/tools?scene_id=${encodeURIComponent(sceneId)}`);
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Tool[];
}

export async function createTool(body: {
  scene_id: string;
  name: string;
  description: string;
  kind: "http" | "plugin";
  config: ToolConfig;
}): Promise<Tool> {
  const resp = await fetch("/api/tools", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Tool;
}

export async function updateTool(
  id: string,
  body: { scene_id: string; name: string; description: string; kind: "http" | "plugin"; config: ToolConfig },
): Promise<Tool> {
  const resp = await fetch(`/api/tools/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Tool;
}

export async function deleteTool(id: string): Promise<void> {
  const resp = await fetch(`/api/tools/${id}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(await _detail(resp));
}

export async function fetchPlugins(): Promise<PluginInfo[]> {
  const resp = await fetch("/api/tools/plugins");
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as PluginInfo[];
}

async function _detail(resp: Response): Promise<string> {
  const body = await resp.json().catch(() => null);
  const detail: unknown = body?.detail;
  return typeof detail === "string" ? detail : `请求失败（${resp.status}）`;
}
