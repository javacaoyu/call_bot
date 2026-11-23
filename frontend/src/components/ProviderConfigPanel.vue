<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  fetchProviderConfig,
  saveProviderConfig,
  type ProviderConfig,
} from "../api/providerConfig";

/** 线路 kind 选项：side 决定状态灯色（local=teal / cloud=blue）。 */
const ASR_KINDS = [
  { value: "funasr", label: "本地 FunASR", side: "local" },
  { value: "volc", label: "火山", side: "cloud" },
  { value: "qwen", label: "千问", side: "cloud" },
] as const;

const TTS_KINDS = [
  { value: "cosyvoice", label: "本地 CosyVoice2", side: "local" },
  { value: "volc", label: "火山", side: "cloud" },
  { value: "qwen", label: "千问", side: "cloud" },
  { value: "aliyun", label: "阿里", side: "cloud" },
] as const;

const cfg = reactive<ProviderConfig>({
  asr_kind: "funasr",
  asr_api_key: "",
  asr_resource_id: "volc.seedasr.sauc.duration",
  tts_kind: "cosyvoice",
  tts_appkey: "",
  tts_token: "",
  tts_access_key_id: "",
  tts_access_key_secret: "",
  tts_voice: "longxiaochun",
  tts_volc_speaker: "zh_female_vv_uranus_bigtts",
  tts_qwen_voice: "longanhuan_v3.1",
  llm_base_url: "",
  llm_api_key: "",
  llm_model: "",
});

const loading = ref(true);
const saving = ref(false);
const saved = ref(false);
const error = ref("");

function sideOf(kind: string, kinds: readonly { value: string; side: string }[]): string {
  return kinds.find((k) => k.value === kind)?.side ?? "local";
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const data = await fetchProviderConfig();
    Object.assign(cfg, data);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function save(): Promise<void> {
  saving.value = true;
  saved.value = false;
  error.value = "";
  try {
    const data = await saveProviderConfig({ ...cfg });
    Object.assign(cfg, data);
    saved.value = true;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="mx-auto my-6 max-w-[720px] rounded-xl border border-line bg-panel p-7 text-text transition-colors">
    <div class="mb-5 flex items-start justify-between gap-4">
      <div>
        <h2 class="text-xl font-semibold">线路配置</h2>
        <p class="mt-1.5 max-w-[46ch] text-[13px] leading-relaxed text-text-dim">
          语音对话引擎的三条走线：识别 → 理解 → 合成。换一条线，下一路会话即生效。
        </p>
      </div>
      <button
        type="button"
        class="shrink-0 rounded-md bg-text px-4.5 py-2 text-sm font-semibold text-bg transition-opacity hover:opacity-85 disabled:cursor-wait disabled:bg-text-faint disabled:text-bg"
        :disabled="saving || loading"
        @click="save"
      >
        {{ saving ? "保存中…" : "保存更改" }}
      </button>
    </div>

    <p v-if="loading" class="text-[13px] text-text-dim">读取当前配置…</p>
    <p v-if="error" class="text-[13px] text-red">{{ error }}</p>
    <p v-if="saved" class="text-[13px] text-teal" role="status">已保存，下一路会话生效</p>

    <template v-if="!loading">
      <!-- ASR 线路 -->
      <section class="mt-4 flex overflow-hidden rounded-lg border border-line bg-panel-2">
        <span
          class="w-1 shrink-0 transition-colors duration-300"
          :class="sideOf(cfg.asr_kind, ASR_KINDS) === 'local' ? 'bg-teal' : 'bg-blue'"
          aria-hidden="true"
        ></span>
        <div class="flex-1 px-5 py-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-[15px] font-semibold">
              语音识别 <span class="ml-1.5 font-mono text-xs font-medium text-text-dim">ASR</span>
            </h3>
            <span
              class="rounded-full border px-2.5 py-0.5 text-xs transition-colors"
              :class="
                sideOf(cfg.asr_kind, ASR_KINDS) === 'local'
                  ? 'border-teal/45 text-teal'
                  : 'border-blue/45 text-blue'
              "
            >
              {{ sideOf(cfg.asr_kind, ASR_KINDS) === "local" ? "本地" : "云端" }}
            </span>
          </div>
          <div class="mb-3 inline-flex overflow-hidden rounded-md border border-line" role="radiogroup" aria-label="语音识别走线">
            <button
              v-for="k in ASR_KINDS"
              :key="k.value"
              type="button"
              class="px-3.5 py-1.5 text-[13px] text-text-dim transition-colors"
              :class="
                cfg.asr_kind === k.value
                  ? 'bg-line text-text'
                  : 'hover:text-text'
              "
              @click="cfg.asr_kind = k.value"
            >
              {{ k.label }}
            </button>
          </div>
          <div v-if="cfg.asr_kind === 'volc'" class="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5 gap-x-3.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              api_key
              <input v-model="cfg.asr_api_key" type="password" placeholder="X-Api-Key" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              资源 ID
              <input v-model="cfg.asr_resource_id" placeholder="volc.seedasr.sauc.duration" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
          </div>
          <div v-else-if="cfg.asr_kind === 'qwen'" class="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              api_key
              <input v-model="cfg.asr_api_key" type="password" placeholder="sk-...（DashScope API Key）" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
          </div>
          <p v-else class="text-[13px] text-text-dim">本地模型，无需密钥。</p>
        </div>
      </section>

      <!-- LLM 线路 -->
      <section class="mt-4 flex overflow-hidden rounded-lg border border-line bg-panel-2">
        <span class="w-1 shrink-0 bg-blue" aria-hidden="true"></span>
        <div class="flex-1 px-5 py-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-[15px] font-semibold">
              大模型 <span class="ml-1.5 font-mono text-xs font-medium text-text-dim">LLM</span>
            </h3>
            <span class="rounded-full border border-blue/45 px-2.5 py-0.5 text-xs text-blue">云端</span>
          </div>
          <p class="mb-3 text-[13px] text-text-dim">
            OpenAI 兼容接口，换端点即换模型：DeepSeek、vLLM、Ollama 都是同一条线。
          </p>
          <div class="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5 gap-x-3.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              端点
              <input v-model="cfg.llm_base_url" placeholder="https://api.deepseek.com" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              密钥
              <input v-model="cfg.llm_api_key" type="password" placeholder="API Key" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              模型名
              <input v-model="cfg.llm_model" placeholder="deepseek-chat" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
          </div>
        </div>
      </section>

      <!-- TTS 线路 -->
      <section class="mt-4 flex overflow-hidden rounded-lg border border-line bg-panel-2">
        <span
          class="w-1 shrink-0 transition-colors duration-300"
          :class="sideOf(cfg.tts_kind, TTS_KINDS) === 'local' ? 'bg-teal' : 'bg-blue'"
          aria-hidden="true"
        ></span>
        <div class="flex-1 px-5 py-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-[15px] font-semibold">
              语音合成 <span class="ml-1.5 font-mono text-xs font-medium text-text-dim">TTS</span>
            </h3>
            <span
              class="rounded-full border px-2.5 py-0.5 text-xs transition-colors"
              :class="
                sideOf(cfg.tts_kind, TTS_KINDS) === 'local'
                  ? 'border-teal/45 text-teal'
                  : 'border-blue/45 text-blue'
              "
            >
              {{ sideOf(cfg.tts_kind, TTS_KINDS) === "local" ? "本地" : "云端" }}
            </span>
          </div>
          <div class="mb-3 inline-flex overflow-hidden rounded-md border border-line" role="radiogroup" aria-label="语音合成走线">
            <button
              v-for="k in TTS_KINDS"
              :key="k.value"
              type="button"
              class="px-3.5 py-1.5 text-[13px] text-text-dim transition-colors"
              :class="
                cfg.tts_kind === k.value
                  ? 'bg-line text-text'
                  : 'hover:text-text'
              "
              @click="cfg.tts_kind = k.value"
            >
              {{ k.label }}
            </button>
          </div>
          <div v-if="cfg.tts_kind === 'volc'" class="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              音色
              <input v-model="cfg.tts_volc_speaker" placeholder="zh_female_vv_uranus_bigtts" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <p class="col-span-full text-[13px] text-text-dim">
              api_key 复用语音识别线路的密钥（火山同一账号 Key 通用）。
            </p>
          </div>
          <div v-else-if="cfg.tts_kind === 'qwen'" class="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              音色
              <input v-model="cfg.tts_qwen_voice" placeholder="longanhuan_v3.1" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <p class="col-span-full text-[13px] text-text-dim">
              api_key 复用语音识别线路的密钥（千问同一账号 Key 通用）。
            </p>
          </div>
          <div v-else-if="cfg.tts_kind === 'aliyun'" class="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5 gap-x-3.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              appkey
              <input v-model="cfg.tts_appkey" placeholder="阿里云 NLS 项目 AppKey" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              token
              <input v-model="cfg.tts_token" type="password" placeholder="临时 token（或留空用 AK/SK）" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              AccessKey ID
              <input v-model="cfg.tts_access_key_id" placeholder="token 留空时使用" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              AccessKey Secret
              <input v-model="cfg.tts_access_key_secret" type="password" placeholder="token 留空时使用" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              音色
              <input v-model="cfg.tts_voice" placeholder="longxiaochun" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
          </div>
          <p v-else class="text-[13px] text-text-dim">本地模型，无需密钥。</p>
        </div>
      </section>
    </template>
  </div>
</template>
