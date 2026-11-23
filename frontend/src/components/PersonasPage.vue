<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  activatePersona,
  createPersona,
  deletePersona,
  fetchPersonas,
  updatePersona,
  type Persona,
} from "../api/personas";
import { fetchScenes, type Scene } from "../api/scenes";

const personas = ref<Persona[]>([]);
const scenes = ref<Scene[]>([]);
const loading = ref(true);
const error = ref("");
const saved = ref("");

/** 编辑表单（showEditor 控制显隐；editing=null 表示新建）。 */
const showEditor = ref(false);
const editing = ref<Persona | null>(null);
const form = reactive({
  name: "",
  description: "",
  system_prompt: "",
  opening: "",
  scene_id: "",
});

function openEditor(p: Persona | null): void {
  editing.value = p;
  form.name = p?.name ?? "";
  form.description = p?.description ?? "";
  form.system_prompt = p?.system_prompt ?? "";
  form.opening = p?.opening ?? "";
  form.scene_id = p?.scene_id ?? scenes.value[0]?.id ?? "";
  showEditor.value = true;
}

function closeEditor(): void {
  showEditor.value = false;
  editing.value = null;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    [personas.value, scenes.value] = await Promise.all([
      fetchPersonas(),
      fetchScenes().catch(() => []),
    ]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function save(): Promise<void> {
  error.value = "";
  saved.value = "";
  try {
    if (editing.value) {
      await updatePersona(editing.value.id, { ...form });
      saved.value = "已保存";
    } else {
      await createPersona({ ...form });
      saved.value = "已创建";
    }
    closeEditor();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function activate(p: Persona): Promise<void> {
  error.value = "";
  try {
    await activatePersona(p.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function remove(p: Persona): Promise<void> {
  error.value = "";
  try {
    await deletePersona(p.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(load);
</script>

<template>
  <div class="mx-auto max-w-[900px] p-5">
    <div class="mb-4 flex items-center justify-between">
      <div>
        <h2 class="text-xl font-semibold">人设管理</h2>
        <p class="mt-1 text-xs text-text-dim">
          Prompt 模板与人设——激活后新会话生效（历史会话不受影响）
        </p>
      </div>
      <button
        class="rounded-md bg-teal px-3.5 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
        @click="openEditor(null)"
      >
        + 新建人设
      </button>
    </div>

    <p v-if="error" class="mb-3 text-xs text-red">{{ error }}</p>
    <p v-if="saved" class="mb-3 text-xs text-teal">{{ saved }}</p>
    <p v-if="loading" class="text-[13px] text-text-dim">读取中…</p>

    <!-- 编辑器 -->
    <div
      v-if="showEditor"
      class="mb-4 rounded-xl border border-line bg-panel p-5 transition-colors"
    >
      <h3 class="mb-3 text-sm font-semibold">
        {{ editing ? `编辑 · ${editing.name}` : "新建人设" }}
      </h3>
      <div class="flex flex-col gap-3">
        <div class="grid grid-cols-2 gap-3">
          <label class="flex flex-col gap-1 text-xs text-text-dim">
            所属场景（从场景库选择）
            <select
              v-model="form.scene_id"
              class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue"
            >
              <option v-for="s in scenes" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </label>
          <label class="flex flex-col gap-1 text-xs text-text-dim">
            人设名
            <input
              v-model="form.name"
              placeholder="如：理财客服小安"
              class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue"
            />
          </label>
        </div>
        <label class="flex flex-col gap-1 text-xs text-text-dim">
          场景说明
          <input
            v-model="form.description"
            placeholder="如：理财产品回访场景，温和专业"
            class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue"
          />
        </label>
        <label class="flex flex-col gap-1 text-xs text-text-dim">
          System Prompt（角色设定与话术边界）
          <textarea
            v-model="form.system_prompt"
            rows="6"
            placeholder="你是一名…"
            class="rounded-md border border-line bg-bg px-2.5 py-2 font-mono text-[13px] leading-relaxed text-text outline-none focus:border-blue"
          ></textarea>
        </label>
        <label class="flex flex-col gap-1 text-xs text-text-dim">
          开场白（可选 · 外呼连接后 AI 首先说的话）
          <textarea
            v-model="form.opening"
            rows="3"
            placeholder="如：{客户姓名}您好，我是XX银行的理财顾问小安，不好意思打扰您一下……"
            class="rounded-md border border-line bg-bg px-2.5 py-2 font-mono text-[13px] leading-relaxed text-text outline-none focus:border-blue"
          ></textarea>
          <span class="text-[11px] text-text-faint">
            模板中出现的 {客户姓名} / {电话号码} / {客户备注} 会在外呼那一刻自动替换；
            留空则由 AI 按人设临场生成开场
          </span>
        </label>
        <div class="flex gap-2">
          <button
            class="rounded-md bg-teal px-4 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
            :disabled="!form.name || !form.system_prompt"
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
    <div class="flex flex-col gap-3">
      <div
        v-for="p in personas"
        :key="p.id"
        class="rounded-xl border bg-panel p-4 transition-colors"
        :class="p.is_active ? 'border-teal/50' : 'border-line'"
      >
        <div class="flex items-center gap-3">
          <span
            class="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]"
            :class="p.is_active ? 'border-teal/45 text-teal' : 'border-line text-text-faint'"
          >
            {{ p.is_active ? "● 使用中" : "未激活" }}
          </span>
          <h4 class="text-sm font-semibold">{{ p.name }}</h4>
          <span
            v-if="p.scene_name"
            class="rounded border border-line px-1.5 py-0.5 text-[10px] text-text-dim"
            >{{ p.scene_name }}</span
          >
          <span class="text-[11px] text-text-faint">{{ p.description }}</span>
          <div class="ml-auto flex gap-2">
            <button
              v-if="!p.is_active"
              class="rounded-md border border-teal/45 px-3 py-1 text-[11px] text-teal transition-colors hover:bg-teal hover:text-white"
              @click="activate(p)"
            >
              激活
            </button>
            <button
              class="rounded-md border border-line bg-panel-2 px-3 py-1 text-[11px] text-text-dim transition-colors hover:text-text"
              @click="openEditor(p)"
            >
              编辑
            </button>
            <button
              class="rounded-md border border-line bg-panel-2 px-3 py-1 text-[11px] text-text-dim transition-colors hover:border-red hover:text-red"
              @click="remove(p)"
            >
              删除
            </button>
          </div>
        </div>
        <pre
          class="mt-3 max-h-24 overflow-y-auto whitespace-pre-wrap rounded-md bg-panel-2 p-3 font-mono text-[12px] leading-relaxed text-text-dim"
        >{{ p.system_prompt }}</pre>
        <div
          v-if="p.opening"
          class="mt-2 rounded-md bg-panel-2 px-3 py-2 font-mono text-[12px] leading-relaxed text-text-dim"
        >
          <span class="text-teal">开场白</span> · {{ p.opening }}
        </div>
      </div>
    </div>
  </div>
</template>
