<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  createScene,
  deleteScene,
  fetchScenes,
  updateScene,
  type Scene,
} from "../api/scenes";

/** 请求 App.vue 切换到流程编排/工具库页并带场景参数 */
const emit = defineEmits<{ navigate: [view: "flow" | "tools", scene: string] }>();
const scenes = ref<Scene[]>([]);
const loading = ref(true);
const error = ref("");
const saved = ref("");
const showEditor = ref(false);
const editing = ref<Scene | null>(null);
const form = reactive({ name: "", description: "" });

function openEditor(s: Scene | null): void {
  editing.value = s;
  form.name = s?.name ?? "";
  form.description = s?.description ?? "";
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
    scenes.value = await fetchScenes();
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
      await updateScene(editing.value.id, { ...form });
      saved.value = "已保存";
    } else {
      await createScene({ ...form });
      saved.value = "已创建";
    }
    closeEditor();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function remove(s: Scene): Promise<void> {
  error.value = "";
  if (!window.confirm(`删除场景「${s.name}」？`)) return;
  try {
    await deleteScene(s.id);
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
        <h2 class="text-xl font-semibold">场景管理</h2>
        <p class="mt-1 text-xs text-text-dim">
          话术资产组织单元——流程图 / 人设 / 工具都挂在场景下；外呼前按场景选择
        </p>
      </div>
      <button
        class="rounded-md bg-teal px-3.5 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
        @click="openEditor(null)"
      >
        + 新建场景
      </button>
    </div>

    <p v-if="error" class="mb-3 text-xs text-red">{{ error }}</p>
    <p v-if="saved" class="mb-3 text-xs text-teal">{{ saved }}</p>
    <p v-if="loading" class="text-[13px] text-text-dim">读取中…</p>

    <!-- 编辑器 -->
    <div v-if="showEditor" class="mb-4 rounded-xl border border-line bg-panel p-5 transition-colors">
      <h3 class="mb-3 text-sm font-semibold">{{ editing ? `编辑 · ${editing.name}` : "新建场景" }}</h3>
      <div class="flex flex-col gap-3">
        <label class="flex flex-col gap-1 text-xs text-text-dim">
          场景名
          <input
            v-model="form.name"
            placeholder="如：理财回访"
            class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue"
          />
        </label>
        <label class="flex flex-col gap-1 text-xs text-text-dim">
          场景说明
          <input
            v-model="form.description"
            placeholder="如：理财产品回访与续费提醒"
            class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue"
          />
        </label>
        <div class="flex gap-2">
          <button
            class="rounded-md bg-teal px-4 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            :disabled="!form.name"
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
        v-for="s in scenes"
        :key="s.id"
        class="rounded-xl border border-line bg-panel p-4 transition-colors"
      >
        <div class="flex items-center gap-3">
          <h4 class="text-sm font-semibold">{{ s.name }}</h4>
          <span class="text-[11px] text-text-faint">{{ s.description || "—" }}</span>
          <div class="ml-auto flex gap-2">
            <button
              class="rounded-md bg-teal px-3 py-1 text-[11px] font-medium text-white transition-opacity hover:opacity-90"
              @click="emit('navigate', 'flow', s.id)"
            >
              流程编排
            </button>
            <button
              class="rounded-md border border-line bg-panel-2 px-3 py-1 text-[11px] text-text-dim transition-colors hover:text-text"
              @click="emit('navigate', 'tools', s.id)"
            >
              工具库
            </button>
            <button
              class="rounded-md border border-line bg-panel-2 px-3 py-1 text-[11px] text-text-dim transition-colors hover:text-text"
              @click="openEditor(s)"
            >
              编辑
            </button>
            <button
              class="rounded-md border border-line bg-panel-2 px-3 py-1 text-[11px] text-text-dim transition-colors hover:border-red hover:text-red"
              @click="remove(s)"
            >
              删除
            </button>
          </div>
        </div>
      </div>
      <p v-if="!loading && scenes.length === 0" class="py-10 text-center text-[13px] text-text-faint">
        暂无场景——点击右上角新建
      </p>
    </div>
  </div>
</template>
