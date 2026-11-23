<script setup lang="ts">
import { onMounted, reactive, ref, watch } from "vue";
import { fetchScenes, type Scene } from "../api/scenes";
import {
  createTool,
  deleteTool,
  fetchPlugins,
  fetchTools,
  updateTool,
  type PluginInfo,
  type Tool,
  type ToolParamSpec,
} from "../api/tools";

const props = defineProps<{ sceneId?: string }>();

const scenes = ref<Scene[]>([]);
const selectedSceneId = ref(props.sceneId ?? "");
const tools = ref<Tool[]>([]);
const plugins = ref<PluginInfo[]>([]);
const loading = ref(true);
const error = ref("");
const saved = ref("");

const showEditor = ref(false);
const editing = ref<Tool | null>(null);
const form = reactive({
  name: "",
  description: "",
  kind: "http" as "http" | "plugin",
  url: "",
  method: "GET",
  plugin: "",
  params: [] as ToolParamSpec[],
  headers: [] as { key: string; value: string }[],
});

const selectedScene = () =>
  scenes.value.find((s) => s.id === selectedSceneId.value) ?? null;

async function loadScenes(): Promise<void> {
  scenes.value = await fetchScenes().catch(() => []);
  if (!selectedSceneId.value && scenes.value.length > 0) {
    selectedSceneId.value = scenes.value[0].id;
  }
}

async function loadTools(): Promise<void> {
  if (!selectedSceneId.value) {
    tools.value = [];
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    [tools.value, plugins.value] = await Promise.all([
      fetchTools(selectedSceneId.value),
      fetchPlugins(),
    ]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function openEditor(t: Tool | null): void {
  editing.value = t;
  form.name = t?.name ?? "";
  form.description = t?.description ?? "";
  form.kind = t?.kind ?? "http";
  form.url = t?.config.url ?? "";
  form.method = t?.config.method ?? "GET";
  form.plugin = t?.config.plugin ?? "";
  form.params = (t?.config.params ?? []).map((p) => ({ ...p }));
  form.headers = Object.entries(t?.config.headers ?? {}).map(([key, value]) => ({
    key,
    value,
  }));
  showEditor.value = true;
}

function closeEditor(): void {
  showEditor.value = false;
  editing.value = null;
}

function addParam(): void {
  form.params.push({ name: "", type: "string", required: false, description: "" });
}

function addHeader(): void {
  form.headers.push({ key: "", value: "" });
}

function buildConfig(): Record<string, unknown> {
  if (form.kind === "plugin") return { plugin: form.plugin };
  return {
    method: form.method,
    url: form.url,
    params: form.params.filter((p) => p.name),
    headers: Object.fromEntries(
      form.headers.filter((h) => h.key).map((h) => [h.key, h.value] as [string, string]),
    ),
  };
}

async function save(): Promise<void> {
  error.value = "";
  saved.value = "";
  if (!selectedSceneId.value) return;
  const payload = {
    scene_id: selectedSceneId.value,
    name: form.name,
    description: form.description,
    kind: form.kind,
    config: buildConfig(),
  };
  try {
    if (editing.value) {
      await updateTool(editing.value.id, payload);
      saved.value = "已保存";
    } else {
      await createTool(payload);
      saved.value = "已创建";
    }
    closeEditor();
    await loadTools();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function remove(t: Tool): Promise<void> {
  error.value = "";
  if (!window.confirm(`删除工具「${t.name}」？`)) return;
  try {
    await deleteTool(t.id);
    await loadTools();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

watch(selectedSceneId, loadTools);
onMounted(async () => {
  await loadScenes();
  await loadTools();
});
</script>

<template>
  <div class="mx-auto max-w-[960px] p-5">
    <div class="mb-4 flex items-center justify-between">
      <div>
        <h2 class="text-xl font-semibold">工具库</h2>
        <p class="mt-1 text-xs text-text-dim">
          handler 子智能体可绑定本场景工具——HTTP 配置式（热生效）或代码插件（重启加载）
        </p>
      </div>
      <div class="flex items-center gap-2">
        <select
          v-model="selectedSceneId"
          class="rounded-md border border-line bg-panel-2 px-2.5 py-1.5 text-xs text-text"
          title="按场景分类"
        >
          <option v-for="s in scenes" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <button
          class="rounded-md bg-teal px-3.5 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          :disabled="!selectedSceneId"
          @click="openEditor(null)"
        >
          + 新建工具
        </button>
      </div>
    </div>

    <p v-if="error" class="mb-3 text-xs text-red">{{ error }}</p>
    <p v-if="saved" class="mb-3 text-xs text-teal">{{ saved }}</p>
    <p v-if="loading" class="text-[13px] text-text-dim">读取中…</p>

    <!-- 编辑器 -->
    <div v-if="showEditor" class="mb-4 rounded-xl border border-line bg-panel p-5 transition-colors">
      <h3 class="mb-3 text-sm font-semibold">{{ editing ? `编辑 · ${editing.name}` : "新建工具" }}</h3>
      <div class="flex flex-col gap-3">
        <div class="grid grid-cols-2 gap-3">
          <label class="flex flex-col gap-1 text-xs text-text-dim">
            工具名
            <input
              v-model="form.name"
              placeholder="如：查订单"
              class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue"
            />
          </label>
          <label class="flex flex-col gap-1 text-xs text-text-dim">
            用途说明（给 LLM：何时该用）
            <input
              v-model="form.description"
              placeholder="如：按订单号查询订单状态与金额"
              class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue"
            />
          </label>
        </div>
        <div class="flex gap-1.5">
          <button
            v-for="kind in ([['http', 'HTTP 配置'], ['plugin', '代码插件']] as const)"
            :key="kind[0]"
            type="button"
            class="rounded-md border px-3 py-1 text-xs transition-colors"
            :class="form.kind === kind[0] ? 'border-teal/50 text-teal' : 'border-line text-text-dim hover:text-text'"
            @click="form.kind = kind[0]"
          >
            {{ kind[1] }}
          </button>
        </div>

        <!-- HTTP 表单 -->
        <template v-if="form.kind === 'http'">
          <div class="grid grid-cols-[110px_1fr] gap-3">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              方法
              <select v-model="form.method" class="rounded-md border border-line bg-bg px-2 py-1.5 text-[13px] text-text">
                <option>GET</option>
                <option>POST</option>
              </select>
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              URL（{参数} 占位）
              <input
                v-model="form.url"
                placeholder="https://api.example.com/orders/{order_id}"
                class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue"
              />
            </label>
          </div>
          <div>
            <div class="mb-1 flex items-center justify-between">
              <span class="text-xs text-text-faint">参数（自动转 schema 给 LLM 填参）</span>
              <button type="button" class="text-[11px] text-teal" @click="addParam">+ 添加参数</button>
            </div>
            <div v-for="(p, i) in form.params" :key="i" class="mb-1.5 grid grid-cols-[1fr_90px_60px_1fr_28px] gap-1.5">
              <input v-model="p.name" placeholder="参数名" class="rounded-md border border-line bg-bg px-2 py-1 font-mono text-[12px] text-text outline-none focus:border-blue" />
              <select v-model="p.type" class="rounded-md border border-line bg-bg px-1.5 py-1 text-[12px] text-text">
                <option value="string">string</option>
                <option value="integer">integer</option>
                <option value="number">number</option>
                <option value="boolean">boolean</option>
              </select>
              <label class="flex items-center justify-center gap-1 rounded-md border border-line bg-bg px-1 py-1 text-[11px] text-text-dim">
                <input v-model="p.required" type="checkbox" class="h-3 w-3" /> 必填
              </label>
              <input v-model="p.description" placeholder="说明" class="rounded-md border border-line bg-bg px-2 py-1 text-[12px] text-text outline-none focus:border-blue" />
              <button type="button" class="text-[11px] text-text-faint hover:text-red" @click="form.params.splice(i, 1)">✕</button>
            </div>
          </div>
          <div>
            <div class="mb-1 flex items-center justify-between">
              <span class="text-xs text-text-faint">Header（如 API key）</span>
              <button type="button" class="text-[11px] text-teal" @click="addHeader">+ 添加</button>
            </div>
            <div v-for="(h, i) in form.headers" :key="i" class="mb-1.5 grid grid-cols-[1fr_1.5fr_28px] gap-1.5">
              <input v-model="h.key" placeholder="key" class="rounded-md border border-line bg-bg px-2 py-1 font-mono text-[12px] text-text outline-none focus:border-blue" />
              <input v-model="h.value" placeholder="value" class="rounded-md border border-line bg-bg px-2 py-1 font-mono text-[12px] text-text outline-none focus:border-blue" />
              <button type="button" class="text-[11px] text-text-faint hover:text-red" @click="form.headers.splice(i, 1)">✕</button>
            </div>
          </div>
        </template>

        <!-- 插件选择 -->
        <template v-else>
          <label class="flex flex-col gap-1 text-xs text-text-dim">
            代码插件（从已加载插件导入；开发规范见 docs/工具插件规范.md）
            <select v-model="form.plugin" class="rounded-md border border-line bg-bg px-2 py-1.5 text-[13px] text-text">
              <option value="">选择插件…</option>
              <option v-for="p in plugins" :key="p.name" :value="p.name">
                {{ p.name }} — {{ p.description }}
              </option>
            </select>
          </label>
          <div v-if="form.plugin" class="rounded-md bg-panel-2 px-3 py-2 text-[12px] text-text-dim">
            参数：
            <span class="font-mono">{{ (plugins.find((p) => p.name === form.plugin)?.params ?? []).map((p) => `${p.name}:${p.type}`).join("，") || "无" }}</span>
          </div>
        </template>

        <div class="flex gap-2">
          <button
            class="rounded-md bg-teal px-4 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            :disabled="!form.name || !form.description || (form.kind === 'http' ? !form.url : !form.plugin)"
            @click="save"
          >
            保存
          </button>
          <button
            class="rounded-md border border-line bg-panel-2 px-4 py-1.5 text-xs text-text-dim transition-colors hover:text-text"
            @click="closeEditor"
          >
            取消
          </button>
        </div>
      </div>
    </div>

    <!-- 列表 -->
    <div class="overflow-hidden rounded-xl border border-line bg-panel transition-colors">
      <div class="grid grid-cols-[1fr_0.7fr_2fr_0.6fr] gap-3 border-b border-line px-4 py-2.5 text-[10px] tracking-[0.08em] text-text-faint">
        <span>工具</span><span>类型</span><span>配置摘要</span><span></span>
      </div>
      <div
        v-for="t in tools"
        :key="t.id"
        class="grid grid-cols-[1fr_0.7fr_2fr_0.6fr] items-center gap-3 border-b border-line px-4 py-3 text-[12.5px] last:border-b-0"
      >
        <div>
          <div class="font-medium">{{ t.name }}</div>
          <div class="text-[11px] text-text-faint">{{ t.description }}</div>
        </div>
        <span class="font-mono text-[11px]">
          <span :class="t.kind === 'plugin' ? 'text-teal' : 'text-blue'">
            {{ t.kind === "plugin" ? "代码插件" : "HTTP" }}
          </span>
        </span>
        <span class="truncate font-mono text-[11px] text-text-dim">
          {{ t.kind === "plugin" ? t.config.plugin : `${t.config.method} ${t.config.url}` }}
        </span>
        <span class="flex justify-end gap-2">
          <button
            class="rounded-md border border-line bg-panel-2 px-2.5 py-1 text-[11px] text-text-dim transition-colors hover:text-text"
            @click="openEditor(t)"
          >
            编辑
          </button>
          <button
            class="rounded-md border border-line bg-panel-2 px-2.5 py-1 text-[11px] text-text-dim transition-colors hover:border-red hover:text-red"
            @click="remove(t)"
          >
            删除
          </button>
        </span>
      </div>
      <p v-if="!loading && tools.length === 0" class="py-10 text-center text-[13px] text-text-faint">
        本场景暂无工具——点击右上角新建（HTTP 配置 / 代码插件导入）
      </p>
    </div>
  </div>
</template>
