<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { Handle, Position, VueFlow, type Connection } from "@vue-flow/core";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "@vue-flow/controls/dist/style.css";
// 注：@vue-flow/background 无独立 style.css（样式内联在组件中）
import {
  createFlow,
  fetchFlow,
  fetchFlowVersions,
  fetchFlows,
  publishFlow,
  rollbackFlow,
  saveDraft,
  type FlowVersionInfo,
} from "../api/flows";
import { fetchScenes, type Scene } from "../api/scenes";
import { fetchTools, type Tool } from "../api/tools";
import {
  NODE_LABEL,
  canConnect,
  defaultPosition,
  defToVueFlow,
  vueFlowToDef,
  type FlowDefinition,
  type FlowNodeType,
  type IntentConfig,
  type VFEdge,
  type VFNode,
} from "../utils/flow";

const props = defineProps<{ sceneId?: string }>();

const scenes = ref<Scene[]>([]);
const selectedSceneId = ref(props.sceneId ?? "");
const sceneTools = ref<Tool[]>([]);
const flowId = ref("");
const flowName = ref("");
const flowDesc = ref("");
const version = ref(0);
const hasUnpublished = ref(false);
const versions = ref<FlowVersionInfo[]>([]);
const rollbackVersion = ref<number | "">("");
const error = ref("");
const notice = ref("");
const publishErrors = ref<string[]>([]);

const nodes = ref<VFNode[]>([]);
const edges = ref<VFEdge[]>([]);

/** 选中元素（属性面板） */
const selected = ref<
  | { kind: "node"; id: string; node: VFNode }
  | { kind: "edge"; id: string; edge: VFEdge }
  | null
>(null);

const selectedNode = computed(() => (selected.value?.kind === "node" ? selected.value.node : null));
const selectedEdge = computed(() => (selected.value?.kind === "edge" ? selected.value.edge : null));

/** 节点 data 强类型读写辅助（data 为可选 Record<string, unknown>，v-model 需显式读写） */
function nodeStr(node: VFNode | null, key: string): string {
  if (!node) return "";
  return String((node.data ?? {})[key] ?? "");
}

function setNodeStr(node: VFNode | null, key: string, value: string): void {
  if (!node) return;
  node.data = { ...(node.data ?? {}), [key]: value };
}

function nodeBool(node: VFNode | null, key: string): boolean {
  if (!node) return false;
  return Boolean((node.data ?? {})[key]);
}

function setNodeBool(node: VFNode | null, key: string, value: boolean): void {
  if (!node) return;
  node.data = { ...(node.data ?? {}), [key]: value };
}

function toolIdsOf(node: VFNode | null): string[] {
  if (!node) return [];
  return ((node.data ?? {}).tool_ids as string[]) ?? [];
}

function toggleTool(node: VFNode | null, toolId: string, checked: boolean): void {
  if (!node) return;
  const ids = toolIdsOf(node);
  setNodeStrList(node, "tool_ids", checked ? [...ids, toolId] : ids.filter((i) => i !== toolId));
}

function setNodeStrList(node: VFNode, key: string, value: string[]): void {
  node.data = { ...(node.data ?? {}), [key]: value };
}
const intentEditable = computed(() => {
  const edge = selectedEdge.value;
  if (!edge) return false;
  const sourceId = String(edge.source); // 收敛 vue-flow 递归泛型（source: string | GraphNode）
  const source = nodes.value.find((n) => n.id === sourceId);
  return source?.data?.nodeType === "intent";
});

const nodeCounts = computed(() => {
  const counts: Record<FlowNodeType, number> = { opening: 0, intent: 0, handler: 0, end: 0 };
  for (const n of nodes.value) {
    const t = n.data?.nodeType as FlowNodeType;
    if (t in counts) counts[t] += 1;
  }
  return counts;
});

let idSeq = 0;
function newId(prefix: string): string {
  idSeq += 1;
  return `${prefix}_${Date.now().toString(36)}_${idSeq}`;
}

// ---------- 加载 ----------

async function loadScenes(): Promise<void> {
  scenes.value = await fetchScenes().catch(() => []);
  if (!selectedSceneId.value && scenes.value.length > 0) {
    selectedSceneId.value = scenes.value[0].id;
  }
}

async function loadFlow(): Promise<void> {
  if (!selectedSceneId.value) return;
  error.value = "";
  try {
    const flows = await fetchFlows(selectedSceneId.value);
    let summary = flows[0];
    if (!summary) {
      const scene = scenes.value.find((s) => s.id === selectedSceneId.value);
      summary = await createFlow({
        scene_id: selectedSceneId.value,
        name: `${scene?.name ?? "新场景"}流程`,
        description: "",
      });
    }
    flowId.value = summary.id;
    flowName.value = summary.name;
    flowDesc.value = summary.description;
    version.value = summary.version;
    hasUnpublished.value = summary.has_unpublished_changes;
    const detail = await fetchFlow(summary.id);
    const vf = defToVueFlow(detail.draft);
    nodes.value = vf.nodes;
    edges.value = vf.edges;
    versions.value = await fetchFlowVersions(summary.id).catch(() => []);
    sceneTools.value = await fetchTools(selectedSceneId.value).catch(() => []);
    selected.value = null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function switchScene(): Promise<void> {
  await loadFlow();
}

// ---------- 画布交互 ----------

function addNodeOfType(type: FlowNodeType): void {
  const data: Record<string, unknown> =
    type === "opening"
      ? { text: "" }
      : type === "handler"
        ? { name: "处理节点", prompt: "", agent_type: "dialog", tool_ids: [], sticky: false }
        : type === "end"
          ? { text: "感谢您的接听，再见。" }
          : {};
  const index = nodeCounts.value[type];
  const id = newId("n");
  nodes.value.push({
    id,
    type: type === "intent" ? "intent-node" : type === "opening" ? "opening-node" : type === "handler" ? "handler-node" : "end-node",
    position: defaultPosition(type, index),
    data: { nodeType: type, ...data },
  });
}

function onConnect(connection: Connection): void {
  const sourceId = String(connection.source);
  const targetId = String(connection.target);
  const source = nodes.value.find((n) => n.id === sourceId);
  const target = nodes.value.find((n) => n.id === targetId);
  const fromType = source?.data?.nodeType as FlowNodeType | undefined;
  const toType = target?.data?.nodeType as FlowNodeType | undefined;
  if (!fromType || !toType || !canConnect(fromType, toType)) {
    error.value = `连线不允许：${NODE_LABEL[fromType ?? "opening"]} → ${NODE_LABEL[toType ?? "opening"]}`;
    return;
  }
  edges.value.push({
    id: newId("e"),
    source: connection.source,
    target: connection.target,
    data: { intent: null },
    label: "",
  } as VFEdge);
}

function onNodeClick(e: { node: VFNode }): void {
  selected.value = { kind: "node", id: e.node.id, node: e.node };
}

function onEdgeClick(e: { edge: VFEdge }): void {
  selected.value = { kind: "edge", id: e.edge.id, edge: e.edge };
  syncIntentForm();
}

function deleteSelected(): void {
  if (!selected.value) return;
  if (selected.value.kind === "node") {
    const id = selected.value.id;
    nodes.value = nodes.value.filter((n) => n.id !== id);
    edges.value = edges.value.filter((e) => e.source !== id && e.target !== id);
  } else {
    edges.value = edges.value.filter((e) => e.id !== selected.value!.id);
  }
  selected.value = null;
}

/** 意图边配置：intent 表单 ↔ edge.data.intent */
const intentForm = reactive({ name: "", keywords: "", description: "" });
const isFallback = ref(false);

function syncIntentForm(): void {
  const edge = selectedEdge.value;
  if (!edge || !intentEditable.value) return;
  const cfg = edge.data?.intent as IntentConfig | null;
  intentForm.name = cfg?.name ?? "";
  intentForm.keywords = cfg?.keywords ?? "";
  intentForm.description = cfg?.description ?? "";
  isFallback.value = !cfg;
}

function applyIntentForm(): void {
  const edge = selectedEdge.value;
  if (!edge || !intentEditable.value) return;
  const name = intentForm.name.trim();
  edge.data = {
    ...(edge.data ?? {}),
    intent: isFallback.value || !name ? null : { ...intentForm, name },
  };
  // 画布连线标签（vue-flow 运行时属性，类型未声明 label）
  (edge as unknown as Record<string, unknown>).label =
    isFallback.value || !name ? "" : name;
  notice.value = "意图配置已更新（记得保存草稿）";
}

// ---------- 保存 / 发布 / 回滚 ----------

function buildDefinition(): FlowDefinition {
  return vueFlowToDef(nodes.value, edges.value);
}

async function save(): Promise<void> {
  error.value = "";
  notice.value = "";
  try {
    const summary = await saveDraft(flowId.value, {
      name: flowName.value,
      description: flowDesc.value,
      draft: buildDefinition(),
    });
    hasUnpublished.value = summary.has_unpublished_changes;
    notice.value = "草稿已保存";
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function publish(): Promise<void> {
  error.value = "";
  notice.value = "";
  publishErrors.value = [];
  try {
    await save();
    const summary = await publishFlow(flowId.value);
    version.value = summary.version;
    hasUnpublished.value = summary.has_unpublished_changes;
    notice.value = `已发布 v${summary.version}`;
    versions.value = await fetchFlowVersions(flowId.value);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    publishErrors.value = msg.split("；");
    error.value = "发布失败：存在校验错误";
  }
}

async function rollback(): Promise<void> {
  error.value = "";
  notice.value = "";
  if (rollbackVersion.value === "") return;
  if (!window.confirm(`回滚到 v${rollbackVersion.value}？将以该版本内容发布为新版本`)) return;
  try {
    await rollbackFlow(flowId.value, Number(rollbackVersion.value));
    await loadFlow();
    notice.value = "已回滚并发布为新版本";
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(async () => {
  await loadScenes();
  await loadFlow();
});
</script>

<template>
  <div class="flex h-[calc(100vh-0px)] min-h-[560px] flex-col">
    <!-- 顶栏：场景 + 保存/发布/回滚 -->
    <div class="flex flex-wrap items-center gap-3 border-b border-line bg-panel px-4 py-2.5">
      <select
        v-model="selectedSceneId"
        class="rounded-md border border-line bg-panel-2 px-2.5 py-1.5 text-xs text-text"
        @change="switchScene"
      >
        <option v-for="s in scenes" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <input
        v-model="flowName"
        class="w-[180px] rounded-md border border-line bg-panel-2 px-2.5 py-1.5 text-xs text-text outline-none focus:border-blue"
        placeholder="流程名"
      />
      <span class="font-mono text-[11px] text-text-dim">
        v{{ version }}<span v-if="hasUnpublished" class="ml-1 text-teal">· 草稿有改动</span>
      </span>
      <select
        v-model="rollbackVersion"
        class="rounded-md border border-line bg-panel-2 px-2 py-1.5 text-xs text-text-dim"
        title="回滚到历史版本"
      >
        <option value="">回滚…</option>
        <option v-for="v in versions" :key="v.version" :value="v.version">
          v{{ v.version }}（{{ v.node_count }}节点）
        </option>
      </select>
      <button
        class="rounded-md border border-line bg-panel-2 px-2.5 py-1 text-[11px] text-text-dim transition-colors hover:text-text"
        :disabled="rollbackVersion === ''"
        @click="rollback"
      >
        回滚
      </button>
      <div class="ml-auto flex gap-2">
        <button
          class="rounded-md border border-line bg-panel-2 px-3.5 py-1.5 text-xs text-text-dim transition-colors hover:text-text"
          @click="save"
        >
          保存草稿
        </button>
        <button
          class="rounded-md bg-teal px-3.5 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
          @click="publish"
        >
          发布
        </button>
      </div>
    </div>

    <p v-if="error" class="border-b border-line bg-panel px-4 py-2 text-xs text-red">{{ error }}</p>
    <p v-if="notice" class="border-b border-line bg-panel px-4 py-2 text-xs text-teal">{{ notice }}</p>
    <div v-if="publishErrors.length" class="border-b border-line bg-panel px-4 py-2">
      <div v-for="(e, i) in publishErrors" :key="i" class="text-xs text-red">· {{ e }}</div>
    </div>

    <div class="flex min-h-0 flex-1">
      <!-- 节点面板 -->
      <div class="w-[150px] shrink-0 space-y-2 border-r border-line bg-panel p-3">
        <div class="text-[10px] tracking-[0.14em] text-text-faint">节点（点击添加）</div>
        <button
          v-for="t in (['opening', 'intent', 'handler', 'end'] as FlowNodeType[])"
          :key="t"
          class="w-full rounded-md border px-2 py-2 text-left text-xs transition-colors"
          :class="(t === 'opening' || t === 'intent') && nodeCounts[t] >= 1
            ? 'cursor-not-allowed border-line text-text-faint opacity-50'
            : 'border-line bg-panel-2 text-text hover:border-teal'"
          :disabled="(t === 'opening' || t === 'intent') && nodeCounts[t] >= 1"
          @click="addNodeOfType(t)"
        >
          <span :class="t === 'opening' ? 'text-teal' : t === 'intent' ? 'text-blue' : t === 'handler' ? 'text-teal' : 'text-red'">●</span>
          {{ NODE_LABEL[t] }}
          <span class="font-mono text-[10px] text-text-faint">×{{ nodeCounts[t] }}</span>
        </button>
        <div class="pt-3 text-[10px] leading-relaxed text-text-faint">
          连线规则：开场白→意图 → 处理/结束；处理→意图（循环）
        </div>
      </div>

      <!-- 画布 -->
      <div class="min-w-0 flex-1 bg-bg">
        <VueFlow
          v-model:nodes="nodes"
          v-model:edges="edges"
          class="h-full"
          @connect="onConnect"
          @node-click="onNodeClick"
          @edge-click="onEdgeClick"
          @pane-click="selected = null"
        >
          <Background />
          <Controls />

          <!-- 自定义节点：slot 名 = 节点 type -->
          <template #node-opening-node="{ data }">
            <div class="rounded-lg border border-teal/60 bg-panel px-3 py-2 shadow-md">
              <div class="text-[11px] font-semibold text-teal">开场白</div>
              <div class="mt-0.5 max-w-[150px] truncate text-[11px] text-text-dim">
                {{ (data.text as string) || "（空 = 人设开场白 / LLM 兜底）" }}
              </div>
              <Handle type="source" :position="Position.Right" />
            </div>
          </template>
          <template #node-intent-node="{ data }">
            <div class="rounded-lg border border-blue/60 bg-panel px-3 py-2 shadow-md">
              <div class="text-[11px] font-semibold text-blue">意图识别</div>
              <div class="mt-0.5 text-[11px] text-text-dim">每轮必经中枢 · 点击出边配置意图</div>
              <Handle type="target" :position="Position.Left" />
              <Handle type="source" :position="Position.Right" />
            </div>
          </template>
          <template #node-handler-node="{ data }">
            <div class="rounded-lg border border-teal/40 bg-panel px-3 py-2 shadow-md">
              <div class="flex items-center gap-1.5 text-[11px] font-semibold text-text">
                {{ (data.name as string) || "处理节点" }}
                <span v-if="data.sticky" class="rounded bg-teal/15 px-1 text-[9px] text-teal">吸附</span>
                <span v-if="(data.tool_ids as string[])?.length" class="rounded bg-blue/15 px-1 text-[9px] text-blue">
                  工具×{{ (data.tool_ids as string[]).length }}
                </span>
              </div>
              <div class="mt-0.5 max-w-[150px] truncate text-[11px] text-text-faint">
                {{ (data.prompt as string) || "（空 = 使用人设）" }}
              </div>
              <Handle type="target" :position="Position.Left" />
              <Handle type="source" :position="Position.Right" />
            </div>
          </template>
          <template #node-end-node="{ data }">
            <div class="rounded-lg border border-red/50 bg-panel px-3 py-2 shadow-md">
              <div class="text-[11px] font-semibold text-red">结束语</div>
              <div class="mt-0.5 max-w-[150px] truncate text-[11px] text-text-dim">
                {{ (data.text as string) || "（无结束语）" }}
              </div>
              <Handle type="target" :position="Position.Left" />
            </div>
          </template>
        </VueFlow>
      </div>

      <!-- 属性面板 -->
      <div class="w-[260px] shrink-0 overflow-y-auto border-l border-line bg-panel p-3">
        <template v-if="selectedNode">
          <div class="mb-2 flex items-center justify-between">
            <div class="text-xs font-semibold">
              {{ NODE_LABEL[selectedNode.data?.nodeType as FlowNodeType] }}
            </div>
            <button class="text-[11px] text-text-faint hover:text-red" @click="deleteSelected">删除</button>
          </div>

          <label
            v-if="selectedNode.data?.nodeType === 'opening' || selectedNode.data?.nodeType === 'end'"
            class="flex flex-col gap-1 text-xs text-text-dim"
          >
            {{ selectedNode.data?.nodeType === "opening" ? "开场白文本（支持 {客户姓名} 等变量；空 = 双轨）" : "结束语文本" }}
            <textarea
              :value="nodeStr(selectedNode, 'text')"
              rows="4"
              class="rounded-md border border-line bg-bg px-2.5 py-2 text-[12px] text-text outline-none focus:border-blue"
              @input="setNodeStr(selectedNode, 'text', ($event.target as HTMLTextAreaElement).value)"
            ></textarea>
          </label>

          <div v-else-if="selectedNode.data?.nodeType === 'handler'" class="flex flex-col gap-2.5">
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              节点名
              <input
                :value="nodeStr(selectedNode, 'name')"
                class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[12px] text-text outline-none focus:border-blue"
                @input="setNodeStr(selectedNode, 'name', ($event.target as HTMLInputElement).value)"
              />
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              本环节话术要求（追加在人设之后，非替代；空 = 仅人设；支持客户变量）
              <textarea
                :value="nodeStr(selectedNode, 'prompt')"
                rows="5"
                class="rounded-md border border-line bg-bg px-2.5 py-2 font-mono text-[12px] leading-relaxed text-text outline-none focus:border-blue"
                @input="setNodeStr(selectedNode, 'prompt', ($event.target as HTMLTextAreaElement).value)"
              ></textarea>
            </label>
            <label class="flex flex-col gap-1 text-xs text-text-dim">
              智能体类型
              <select
                :value="nodeStr(selectedNode, 'agent_type') || 'dialog'"
                class="rounded-md border border-line bg-bg px-2 py-1.5 text-[12px] text-text"
                @change="setNodeStr(selectedNode, 'agent_type', ($event.target as HTMLSelectElement).value)"
              >
                <option value="dialog">对话智能体</option>
                <option value="tool">工具调用智能体</option>
              </select>
            </label>
            <div>
              <div class="mb-1 text-xs text-text-faint">绑定工具（本场景工具库）</div>
              <label v-for="t in sceneTools" :key="t.id" class="flex items-center gap-1.5 py-0.5 text-[12px] text-text-dim">
                <input
                  type="checkbox"
                  class="h-3 w-3"
                  :checked="toolIdsOf(selectedNode).includes(t.id)"
                  @change="toggleTool(selectedNode, t.id, ($event.target as HTMLInputElement).checked)"
                />
                {{ t.name }}<span class="font-mono text-[10px] text-text-faint">{{ t.kind === "plugin" ? "插件" : "HTTP" }}</span>
              </label>
              <p v-if="sceneTools.length === 0" class="text-[11px] text-text-faint">本场景暂无工具（去「工具库」新建）</p>
            </div>
            <label class="flex items-center gap-1.5 text-xs text-text-dim">
              <input
                type="checkbox"
                class="h-3 w-3"
                :checked="nodeBool(selectedNode, 'sticky')"
                @change="setNodeBool(selectedNode, 'sticky', ($event.target as HTMLInputElement).checked)"
              />
              吸附模式（未命中关键词时不重新识别意图，留在本节点追问）
            </label>
          </div>

          <p v-else class="text-xs text-text-faint">意图在「出边」上配置——点击画布中的意图连线</p>
        </template>

        <template v-else-if="selectedEdge">
          <div class="mb-2 flex items-center justify-between">
            <div class="text-xs font-semibold">连线</div>
            <button class="text-[11px] text-text-faint hover:text-red" @click="deleteSelected">删除</button>
          </div>
          <div v-if="intentEditable" class="flex flex-col gap-2.5">
            <label class="flex items-center gap-1.5 text-xs text-text-dim">
              <input v-model="isFallback" type="checkbox" class="h-3 w-3" @change="applyIntentForm" />
              兜底边（意图未命中时走这条，至多一条）
            </label>
            <template v-if="!isFallback">
              <label class="flex flex-col gap-1 text-xs text-text-dim">
                意图名
                <input v-model="intentForm.name" placeholder="如：投诉" class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[12px] text-text outline-none focus:border-blue" />
              </label>
              <label class="flex flex-col gap-1 text-xs text-text-dim">
                关键词（逗号分隔，本地快路径）
                <input v-model="intentForm.keywords" placeholder="如：投诉,差评,退款" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[12px] text-text outline-none focus:border-blue" />
              </label>
              <label class="flex flex-col gap-1 text-xs text-text-dim">
                描述（给 LLM 分类的依据）
                <textarea v-model="intentForm.description" rows="3" placeholder="如：客户表达不满或要求投诉" class="rounded-md border border-line bg-bg px-2.5 py-2 text-[12px] text-text outline-none focus:border-blue"></textarea>
              </label>
            </template>
            <button
              class="rounded-md bg-teal px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
              @click="applyIntentForm"
            >
              应用意图配置
            </button>
          </div>
          <p v-else class="text-xs text-text-faint">结构连线（无意图配置）</p>
        </template>

        <p v-else class="text-xs text-text-faint">
          点击节点或连线编辑属性；左侧面板添加节点，拖拽连线建立流程
        </p>
      </div>
    </div>
  </div>
</template>
