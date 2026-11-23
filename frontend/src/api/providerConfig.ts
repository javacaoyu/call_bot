/** Provider 配置 API：三环节（ASR/LLM/TTS）走线配置的读取与保存。 */

export interface ProviderConfig {
  asr_kind: string;
  asr_volc_api_key: string;
  asr_qwen_api_key: string;
  asr_resource_id: string;
  asr_qwen_model: string;
  tts_kind: string;
  tts_volc_speaker: string;
  tts_qwen_voice: string;
  llm_base_url: string;
  llm_api_key: string;
  llm_model: string;
}

export async function fetchProviderConfig(): Promise<ProviderConfig> {
  const resp = await fetch("/api/provider_config");
  if (!resp.ok) {
    throw new Error(`读取配置失败（${resp.status}）`);
  }
  return (await resp.json()) as ProviderConfig;
}

export async function saveProviderConfig(
  values: Partial<ProviderConfig>,
): Promise<ProviderConfig> {
  const resp = await fetch("/api/provider_config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    const detail: string | undefined = body?.detail;
    throw new Error(detail ?? `保存配置失败（${resp.status}）`);
  }
  return (await resp.json()) as ProviderConfig;
}
