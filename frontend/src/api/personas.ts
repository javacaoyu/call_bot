/** 人设管理 API（WBS 6.1）：Prompt 模板 CRUD 与激活。 */

export interface Persona {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  /** 开场白模板（6.2）：空串 = 未配置，由 LLM 按人设兜底生成 */
  opening: string;
  is_active: boolean;
  created_at: string;
}

export async function fetchVariables(): Promise<Record<string, string>> {
  const resp = await fetch("/api/personas/variables");
  if (!resp.ok) throw new Error(`读取变量失败（${resp.status}）`);
  return (await resp.json()) as Record<string, string>;
}

export async function fetchPersonas(): Promise<Persona[]> {
  const resp = await fetch("/api/personas");
  if (!resp.ok) throw new Error(`读取人设失败（${resp.status}）`);
  return (await resp.json()) as Persona[];
}

export async function createPersona(
  body: Omit<Persona, "id" | "is_active" | "created_at">,
): Promise<Persona> {
  const resp = await fetch("/api/personas", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Persona;
}

export async function updatePersona(
  id: string,
  body: Omit<Persona, "id" | "is_active" | "created_at">,
): Promise<Persona> {
  const resp = await fetch(`/api/personas/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Persona;
}

export async function deletePersona(id: string): Promise<void> {
  const resp = await fetch(`/api/personas/${id}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(await _detail(resp));
}

export async function activatePersona(id: string): Promise<Persona> {
  const resp = await fetch(`/api/personas/${id}/activate`, { method: "POST" });
  if (!resp.ok) throw new Error(await _detail(resp));
  return (await resp.json()) as Persona;
}

async function _detail(resp: Response): Promise<string> {
  const body = await resp.json().catch(() => null);
  const detail: unknown = body?.detail;
  return typeof detail === "string" ? detail : `请求失败（${resp.status}）`;
}
