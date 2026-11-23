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
] as const;

/** 音色列表（5.2）：各 TTS provider 的常用音色 + 自定义兜底。 */
/** 火山豆包语音合成 2.0 音色（官方音色列表验证，外呼场景精选）。 */
const VOLC_VOICES = [
  { value: "zh_female_vv_uranus_bigtts", label: "Vivi 女声（默认）" },
  { value: "zh_female_qinqienv_uranus_bigtts", label: "亲切女声" },
  { value: "zh_female_tiexinnvsheng_uranus_bigtts", label: "贴心女生" },
  { value: "zh_female_wenroushunv_uranus_bigtts", label: "温柔淑女" },
  { value: "zh_female_shuangkuaisisi_moon_bigtts", label: "爽快女声" },
  { value: "zh_male_wennuanahu_uranus_bigtts", label: "温暖男声" },
  { value: "zh_male_wenrouxiaoge_uranus_bigtts", label: "温柔小哥" },
  { value: "zh_male_qingshuangnanda_uranus_bigtts", label: "清爽男声" },
];
const VOLC_VOICE_VALUES = VOLC_VOICES.map((v) => v.value);
/** 千问 Qwen-Audio-TTS 系统音色（逐个实测 HTTP 200 验证，特质标注）。 */
const QWEN_VOICES = [
  { value: "longanhuan_v3.1", label: "欢快 · 女声（默认）" },
  { value: "longanlingxin_v3.1", label: "知心温暖 · 女声" },
  { value: "longanfengyue_v3.1", label: "自然亲切 · 女声" },
  { value: "longanlingxi_v3.1", label: "可爱甜美 · 女声" },
  { value: "longanyuanfei_v3.1", label: "高傲妃子 · 女声" },
  { value: "longanwen_v3.1", label: "文静 · 女声" },
  { value: "longanyang_v3.1", label: "阳光 · 男声" },
  { value: "longanzhi_v3.1", label: "知性 · 女声" },
  { value: "longanlang_v3.1", label: "朗朗 · 男声" },
  { value: "longanli_v3.1", label: "利落 · 男声" },
  { value: "longanya_v3.1", label: "雅致 · 女声" },
  { value: "longanchong_v3.1", label: "宠溺 · 男声" },
];
const QWEN_VOICE_VALUES = QWEN_VOICES.map((v) => v.value);

/** 模型版本（5.2）：火山资源 / 千问 ASR 模型 / LLM 模型。 */
const VOLC_RESOURCE_IDS = [
  { value: "volc.seedasr.sauc.duration", label: "识别 2.0 · 时长版" },
  { value: "volc.seedasr.sauc.concurrent", label: "识别 2.0 · 并发版" },
];
const QWEN_ASR_MODELS = [
  { value: "qwen-audio-3.1-asr-flash-streaming", label: "实时版（中间结果）" },
  { value: "qwen-audio-3.1-asr-flash-message", label: "短句版（仅最终结果）" },
];
const LLM_MODELS = ["deepseek-chat", "deepseek-reasoner"];


const cfg = reactive<ProviderConfig>({
  asr_kind: "funasr",
  asr_volc_api_key: "",
  asr_qwen_api_key: "",
  asr_resource_id: "volc.seedasr.sauc.duration",
  asr_qwen_model: "qwen-audio-3.1-asr-flash-streaming",
  tts_kind: "cosyvoice",
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
              <input v-model="cfg.asr_volc_api_key" type="password" placeholder="火山 X-Api-Key" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              模型版本
              <select v-model="cfg.asr_resource_id" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue">
                <option v-for="r in VOLC_RESOURCE_IDS" :key="r.value" :value="r.value">{{ r.label }}</option>
              </select>
            </label>
          </div>
          <div v-else-if="cfg.asr_kind === 'qwen'" class="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              api_key
              <input v-model="cfg.asr_qwen_api_key" type="password" placeholder="sk-...（DashScope API Key）" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              模型
              <select v-model="cfg.asr_qwen_model" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue">
                <option v-for="m in QWEN_ASR_MODELS" :key="m.value" :value="m.value">{{ m.label }}</option>
              </select>
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
              模型
              <select
                :value="LLM_MODELS.includes(cfg.llm_model) ? cfg.llm_model : '__custom__'"
                class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue"
                @change="(e: Event) => { const v = (e.target as HTMLSelectElement).value; if (v !== '__custom__') cfg.llm_model = v; }"
              >
                <option v-for="m in LLM_MODELS" :key="m" :value="m">{{ m }}</option>
                <option value="__custom__">自定义…</option>
              </select>
            </label>
            <label v-if="!LLM_MODELS.includes(cfg.llm_model)" class="flex flex-col gap-1 text-xs text-text-dim">
              自定义模型名
              <input v-model="cfg.llm_model" placeholder="输入模型 ID" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
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
              <select
                :value="VOLC_VOICE_VALUES.includes(cfg.tts_volc_speaker) ? cfg.tts_volc_speaker : '__custom__'"
                class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue"
                @change="(e: Event) => { const v = (e.target as HTMLSelectElement).value; if (v !== '__custom__') cfg.tts_volc_speaker = v; }"
              >
                <option v-for="v in VOLC_VOICES" :key="v.value" :value="v.value">{{ v.label }}（{{ v.value }}）</option>
                <option value="__custom__">自定义…</option>
              </select>
            </label>
            <label v-if="!VOLC_VOICE_VALUES.includes(cfg.tts_volc_speaker)" class="flex flex-col gap-1 text-xs text-text-dim">
              自定义音色 ID
              <input v-model="cfg.tts_volc_speaker" placeholder="音色 ID" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <p class="col-span-full text-[13px] text-text-dim">
              api_key 复用语音识别线路的密钥（火山同一账号 Key 通用）。
            </p>
          </div>
          <div v-else-if="cfg.tts_kind === 'qwen'" class="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              音色
              <select
                :value="QWEN_VOICE_VALUES.includes(cfg.tts_qwen_voice) ? cfg.tts_qwen_voice : '__custom__'"
                class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue"
                @change="(e: Event) => { const v = (e.target as HTMLSelectElement).value; if (v !== '__custom__') cfg.tts_qwen_voice = v; }"
              >
                <option v-for="v in QWEN_VOICES" :key="v.value" :value="v.value">{{ v.label }}（{{ v.value }}）</option>
                <option value="__custom__">自定义…</option>
              </select>
            </label>
            <label v-if="!QWEN_VOICE_VALUES.includes(cfg.tts_qwen_voice)" class="flex flex-col gap-1 text-xs text-text-dim">
              自定义音色
              <input v-model="cfg.tts_qwen_voice" placeholder="音色 ID" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
            </label>
            <p class="col-span-full text-[13px] text-text-dim">
              api_key 复用语音识别线路的密钥（千问同一账号 Key 通用）。
            </p>
          </div>
          <p v-else class="text-[13px] text-text-dim">
            本地 CosyVoice2 使用参考音频克隆音色，无需密钥。
          </p>
        </div>
      </section>
    </template>
  </div>
</template>
