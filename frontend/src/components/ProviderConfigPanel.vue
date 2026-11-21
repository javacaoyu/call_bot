<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  fetchProviderConfig,
  saveProviderConfig,
  type ProviderConfig,
} from "../api/providerConfig";

/** 线路 kind 选项：side 决定状态灯色（local=琥珀 / cloud=蓝）。 */
const ASR_KINDS = [
  { value: "funasr", label: "本地 FunASR", side: "local" },
  { value: "xfyun", label: "讯飞", side: "cloud" },
  { value: "volc", label: "火山", side: "cloud" },
] as const;

const TTS_KINDS = [
  { value: "cosyvoice", label: "本地 CosyVoice2", side: "local" },
  { value: "volc", label: "火山", side: "cloud" },
  { value: "aliyun", label: "阿里", side: "cloud" },
] as const;

const cfg = reactive<ProviderConfig>({
  asr_kind: "funasr",
  asr_app_id: "",
  asr_api_key: "",
  asr_api_secret: "",
  asr_resource_id: "volc.seedasr.sauc.duration",
  tts_kind: "cosyvoice",
  tts_appkey: "",
  tts_token: "",
  tts_access_key_id: "",
  tts_access_key_secret: "",
  tts_voice: "longxiaochun",
  tts_volc_speaker: "zh_female_vv_uranus_bigtts",
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
  <div class="panel">
    <div class="panel-head">
      <div>
        <h2>线路配置</h2>
        <p class="panel-sub">
          语音对话引擎的三条走线：识别 → 理解 → 合成。换一条线，下一路会话即生效。
        </p>
      </div>
      <button
        type="button"
        class="save-btn"
        :disabled="saving || loading"
        @click="save"
      >
        {{ saving ? "保存中…" : "保存更改" }}
      </button>
    </div>

    <p v-if="loading" class="panel-note">读取当前配置…</p>
    <p v-if="error" class="panel-error">{{ error }}</p>
    <p v-if="saved" class="panel-saved" role="status">已保存，下一路会话生效</p>

    <template v-if="!loading">
      <!-- ASR 线路 -->
      <section class="line-card">
        <span
          class="line-strip"
          :class="sideOf(cfg.asr_kind, ASR_KINDS)"
          aria-hidden="true"
        ></span>
        <div class="line-body">
          <div class="line-head">
            <h3>语音识别 <span class="line-role">ASR</span></h3>
            <span class="lamp" :class="sideOf(cfg.asr_kind, ASR_KINDS)">
              {{ sideOf(cfg.asr_kind, ASR_KINDS) === "local" ? "本地" : "云端" }}
            </span>
          </div>
          <div class="segmented" role="radiogroup" aria-label="语音识别走线">
            <button
              v-for="k in ASR_KINDS"
              :key="k.value"
              type="button"
              :class="{ on: cfg.asr_kind === k.value }"
              @click="cfg.asr_kind = k.value"
            >
              {{ k.label }}
            </button>
          </div>
          <div v-if="cfg.asr_kind === 'xfyun'" class="fields">
            <label>app_id<input v-model="cfg.asr_app_id" placeholder="讯飞控制台应用 ID" /></label>
            <label>api_key<input v-model="cfg.asr_api_key" type="password" placeholder="APIKey" /></label>
            <label>api_secret<input v-model="cfg.asr_api_secret" type="password" placeholder="APISecret" /></label>
          </div>
          <div v-else-if="cfg.asr_kind === 'volc'" class="fields">
            <label>api_key<input v-model="cfg.asr_api_key" type="password" placeholder="X-Api-Key" /></label>
            <label>资源 ID<input v-model="cfg.asr_resource_id" placeholder="volc.seedasr.sauc.duration" /></label>
          </div>
          <p v-else class="line-note">本地模型，无需密钥。</p>
        </div>
      </section>

      <!-- LLM 线路 -->
      <section class="line-card">
        <span class="line-strip cloud" aria-hidden="true"></span>
        <div class="line-body">
          <div class="line-head">
            <h3>大模型 <span class="line-role">LLM</span></h3>
            <span class="lamp cloud">云端</span>
          </div>
          <p class="line-note llm-note">
            OpenAI 兼容接口，换端点即换模型：DeepSeek、vLLM、Ollama 都是同一条线。
          </p>
          <div class="fields">
            <label>端点<input v-model="cfg.llm_base_url" placeholder="https://api.deepseek.com" /></label>
            <label>密钥<input v-model="cfg.llm_api_key" type="password" placeholder="API Key" /></label>
            <label>模型名<input v-model="cfg.llm_model" placeholder="deepseek-chat" /></label>
          </div>
        </div>
      </section>

      <!-- TTS 线路 -->
      <section class="line-card">
        <span
          class="line-strip"
          :class="sideOf(cfg.tts_kind, TTS_KINDS)"
          aria-hidden="true"
        ></span>
        <div class="line-body">
          <div class="line-head">
            <h3>语音合成 <span class="line-role">TTS</span></h3>
            <span class="lamp" :class="sideOf(cfg.tts_kind, TTS_KINDS)">
              {{ sideOf(cfg.tts_kind, TTS_KINDS) === "local" ? "本地" : "云端" }}
            </span>
          </div>
          <div class="segmented" role="radiogroup" aria-label="语音合成走线">
            <button
              v-for="k in TTS_KINDS"
              :key="k.value"
              type="button"
              :class="{ on: cfg.tts_kind === k.value }"
              @click="cfg.tts_kind = k.value"
            >
              {{ k.label }}
            </button>
          </div>
          <div v-if="cfg.tts_kind === 'volc'" class="fields">
            <label>音色<input v-model="cfg.tts_volc_speaker" placeholder="zh_female_vv_uranus_bigtts" /></label>
            <p class="line-note" style="grid-column: 1 / -1">
              api_key 复用语音识别线路的密钥（火山同一账号 Key 通用）。
            </p>
          </div>
          <div v-else-if="cfg.tts_kind === 'aliyun'" class="fields">
            <label>appkey<input v-model="cfg.tts_appkey" placeholder="阿里云 NLS 项目 AppKey" /></label>
            <label>token<input v-model="cfg.tts_token" type="password" placeholder="临时 token（或留空用 AK/SK）" /></label>
            <label>AccessKey ID<input v-model="cfg.tts_access_key_id" placeholder="token 留空时使用" /></label>
            <label>AccessKey Secret<input v-model="cfg.tts_access_key_secret" type="password" placeholder="token 留空时使用" /></label>
            <label>音色<input v-model="cfg.tts_voice" placeholder="longxiaochun" /></label>
          </div>
          <p v-else class="line-note">本地模型，无需密钥。</p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.panel {
  max-width: 720px;
  margin: 24px auto;
  padding: 28px;
  background: #161b22;
  border: 1px solid #2a333d;
  border-radius: 10px;
  color: #e6ebf0;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

.panel-head h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.panel-sub {
  margin: 6px 0 0;
  color: #8b98a5;
  font-size: 13px;
  line-height: 1.5;
  max-width: 46ch;
}

.save-btn {
  flex-shrink: 0;
  background: #e6ebf0;
  color: #161b22;
  font-weight: 600;
  padding: 9px 18px;
  border-radius: 6px;
}

.save-btn:hover:not(:disabled) {
  background: #ffffff;
}

.save-btn:disabled {
  background: #3a4550;
  color: #8b98a5;
  cursor: wait;
}

.panel-note {
  color: #8b98a5;
  font-size: 13px;
}

.panel-error {
  color: #e5484d;
  font-size: 13px;
}

.panel-saved {
  color: #e8a33d;
  font-size: 13px;
}

.line-card {
  display: flex;
  background: #1f262e;
  border: 1px solid #2a333d;
  border-radius: 8px;
  margin-top: 16px;
  overflow: hidden;
}

.line-strip {
  flex-shrink: 0;
  width: 4px;
  transition: background-color 0.3s ease;
}

.line-strip.local {
  background: #e8a33d;
}

.line-strip.cloud {
  background: #4d9de0;
}

.line-body {
  flex: 1;
  padding: 16px 20px 18px;
}

.line-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.line-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.line-role {
  color: #8b98a5;
  font-size: 12px;
  font-weight: 500;
  margin-left: 6px;
  font-variant-numeric: tabular-nums;
}

.lamp {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid transparent;
  transition: color 0.3s ease, border-color 0.3s ease;
}

.lamp.local {
  color: #e8a33d;
  border-color: rgba(232, 163, 61, 0.45);
}

.lamp.cloud {
  color: #4d9de0;
  border-color: rgba(77, 157, 224, 0.45);
}

.segmented {
  display: inline-flex;
  border: 1px solid #2a333d;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 12px;
}

.segmented button {
  background: transparent;
  color: #8b98a5;
  border: none;
  border-radius: 0;
  padding: 7px 14px;
  font-size: 13px;
  margin: 0;
}

.segmented button + button {
  border-left: 1px solid #2a333d;
}

.segmented button.on {
  background: #2a333d;
  color: #e6ebf0;
}

.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px 14px;
}

.fields label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #8b98a5;
}

.fields input {
  background: #161b22;
  border: 1px solid #2a333d;
  border-radius: 5px;
  color: #e6ebf0;
  padding: 7px 10px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.fields input:focus {
  outline: 2px solid #4d9de0;
  outline-offset: 0;
  border-color: #4d9de0;
}

.fields input::placeholder {
  color: #4b5865;
}

.line-note {
  margin: 0;
  color: #8b98a5;
  font-size: 13px;
}

.llm-note {
  margin-bottom: 12px;
}

@media (max-width: 640px) {
  .panel {
    padding: 18px;
  }
  .panel-head {
    flex-direction: column;
  }
}
</style>
