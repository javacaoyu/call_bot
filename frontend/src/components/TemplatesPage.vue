<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  fetchTemplates,
  instantiateTemplate,
  type TemplateSummary,
} from "../api/templates";

/** 请求 App.vue 跳到新实例化场景的流程编排 */
const emit = defineEmits<{ navigate: [view: "flow", scene: string] }>();

const templates = ref<TemplateSummary[]>([]);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const busyKey = ref("");

const INDUSTRY_COLOR: Record<string, string> = {
  营销: "text-blue",
  催收: "text-red",
  回访: "text-teal",
  通知: "text-blue",
  客服: "text-teal",
};

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    templates.value = await fetchTemplates();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function use(t: TemplateSummary): Promise<void> {
  error.value = "";
  notice.value = "";
  if (!window.confirm(`使用模板「${t.name}」？将创建独立场景（人设 + 已发布流程图），可随意修改。`)) return;
  busyKey.value = t.key;
  try {
    const result = await instantiateTemplate(t.key);
    notice.value = `已创建场景「${result.scene_name}」（流程 v${result.flow_version} 已发布）`;
    // 跳转到该场景的流程编排（可微调后重新发布）
    emit("navigate", "flow", result.scene_id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busyKey.value = "";
  }
}

onMounted(load);
</script>

<template>
  <div class="mx-auto max-w-[960px] p-5">
    <div class="mb-4">
      <h2 class="text-xl font-semibold">模板库</h2>
      <p class="mt-1 text-xs text-text-dim">
        预置 5 大行业完整场景包（人设 + 流程图 + 话术）——一键实例化，再按需微调
      </p>
    </div>

    <p v-if="error" class="mb-3 text-xs text-red">{{ error }}</p>
    <p v-if="notice" class="mb-3 text-xs text-teal">{{ notice }}</p>
    <p v-if="loading" class="text-[13px] text-text-dim">读取中…</p>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div
        v-for="t in templates"
        :key="t.key"
        class="rounded-xl border border-line bg-panel p-4 transition-colors hover:border-teal/40"
      >
        <div class="flex items-center gap-2">
          <span
            class="rounded border border-line px-1.5 py-0.5 text-[10px]"
            :class="INDUSTRY_COLOR[t.industry] ?? 'text-text-dim'"
            >{{ t.industry }}</span
          >
          <h4 class="text-sm font-semibold">{{ t.name }}</h4>
        </div>
        <p class="mt-1.5 text-[12px] leading-relaxed text-text-dim">{{ t.description }}</p>
        <div class="mt-2.5 flex items-center gap-3 font-mono text-[11px] text-text-faint">
          <span>人设：{{ t.persona_name }}</span>
          <span>处理节点 ×{{ t.handler_count }}</span>
          <span>意图 ×{{ t.intent_count }}</span>
        </div>
        <button
          class="mt-3 w-full rounded-md bg-teal px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          :disabled="busyKey !== ''"
          @click="use(t)"
        >
          {{ busyKey === t.key ? "创建中…" : "使用此模板" }}
        </button>
      </div>
    </div>

    <p
      v-if="!loading && templates.length === 0"
      class="py-10 text-center text-[13px] text-text-faint"
    >
      暂无模板
    </p>
  </div>
</template>
