/** 场景管理 API（WBS 6.3）：话术资产组织单元。 */

export interface Scene {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export async function fetchScenes(): Promise<Scene[]> {
  const resp = await fetch("/api/scenes");
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Scene[];
}

export async function createScene(body: {
  name: string;
  description: string;
}): Promise<Scene> {
  const resp = await fetch("/api/scenes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Scene;
}

export async function updateScene(
  id: string,
  body: { name: string; description: string },
): Promise<Scene> {
  const resp = await fetch(`/api/scenes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Scene;
}

export async function deleteScene(id: string): Promise<void> {
  const resp = await fetch(`/api/scenes/${id}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(await _detail(resp));
}

async function _detail(resp: Response): Promise<string> {
  const body = await resp.json().catch(() => null);
  const detail: unknown = body?.detail;
  return typeof detail === "string" ? detail : `请求失败（${resp.status}）`;
}
