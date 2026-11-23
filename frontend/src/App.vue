<script setup lang="ts">
import { ref } from "vue";
import CallsPage from "./components/CallsPage.vue";
import CustomersPage from "./components/CustomersPage.vue";
import FlowEditorPage from "./components/FlowEditorPage.vue";
import PersonasPage from "./components/PersonasPage.vue";
import ProviderConfigPanel from "./components/ProviderConfigPanel.vue";
import ScenesPage from "./components/ScenesPage.vue";
import TemplatesPage from "./components/TemplatesPage.vue";
import ToolsPage from "./components/ToolsPage.vue";
import WebRtcSession from "./components/WebRtcSession.vue";

type View =
  | "chat"
  | "config"
  | "records"
  | "personas"
  | "customers"
  | "scenes"
  | "tools"
  | "flow"
  | "templates";

interface NavItem {
  id: View | string;
  label: string;
  badge?: string;
  soon?: boolean;
  icon: string;
}

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "运营",
    items: [
      { id: "chat", label: "对话工作台", badge: "LIVE", icon: "chat" },
      { id: "records", label: "通话记录", icon: "records" },
      { id: "customers", label: "客户管理", icon: "tpl" },
      { id: "scenes", label: "场景管理", icon: "tpl" },
    ],
  },
  {
    label: "配置",
    items: [
      { id: "config", label: "线路配置", icon: "lines" },
      { id: "personas", label: "人设管理", icon: "tpl" },
      { id: "flow", label: "话术编排", icon: "flow" },
      { id: "tools", label: "工具库", icon: "flow" },
      { id: "templates", label: "模板库", icon: "tpl" },
      { id: "kb", label: "知识库", soon: true, icon: "kb" },
    ],
  },
  {
    label: "治理",
    items: [
      { id: "compliance", label: "合规中心", soon: true, icon: "shield" },
      { id: "monitor", label: "监控", soon: true, icon: "monitor" },
    ],
  },
];

const view = ref<View>("chat");
/** 页面上下文参数（流程编排/工具库的当前场景 id） */
const pageScene = ref("");

function navigate(next: View, scene = ""): void {
  view.value = next;
  pageScene.value = scene;
}
const theme = ref(
  localStorage.getItem("callbot-theme") === "light" ? "light" : "dark",
);

function applyTheme(next: string): void {
  theme.value = next;
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("callbot-theme", next);
}
applyTheme(theme.value);
</script>

<template>
  <div class="flex min-h-screen bg-bg text-text">
    <!-- ======== 左侧选项卡 ======== -->
    <aside
      class="sticky top-0 h-screen w-[224px] shrink-0 flex flex-col border-r border-line bg-panel/60 backdrop-blur"
    >
      <!-- 品牌 -->
      <div class="flex items-center gap-3 px-5 pt-6 pb-5">
        <span class="h-2 w-2 rounded-full bg-teal animate-lamp"></span>
        <div>
          <div class="text-[15px] font-bold leading-tight">callbot</div>
          <div class="text-[11px] text-text-faint">外呼语音引擎</div>
        </div>
      </div>

      <!-- 导航 -->
      <nav class="flex-1 overflow-y-auto px-3 pb-4">
        <div v-for="group in NAV_GROUPS" :key="group.label" class="mt-2">
          <div
            class="px-3 pt-4 pb-1.5 text-[10px] tracking-[0.14em] text-text-faint"
          >
            {{ group.label }}
          </div>
          <a
            v-for="item in group.items"
            :key="item.id"
            href="#"
            class="group flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors"
            :class="[
              view === item.id
                ? 'bg-panel-2 text-text shadow-[inset_2px_0_0_var(--teal)]'
                : item.soon
                  ? 'cursor-not-allowed text-text-faint opacity-60'
                  : 'text-text-dim hover:bg-panel-2 hover:text-text',
            ]"
            @click.prevent="!item.soon && navigate(item.id as View)"
          >
            <!-- 图标 -->
            <svg
              v-if="item.icon === 'chat'"
              class="h-4 w-4"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"
            ><path d="M2 3h12v10H2z" /><path d="M5 6h6M5 9h4" /></svg>
            <svg
              v-else-if="item.icon === 'records'"
              class="h-4 w-4"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"
            ><path d="M4 2v12M4 4h9v8H4z" /><path d="M6.5 7h4M6.5 10h3" /></svg>
            <svg
              v-else-if="item.icon === 'lines'"
              class="h-4 w-4"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"
            ><path d="M2 4h5M10 4h4M2 12h5M10 12h4" /><circle cx="8.5" cy="4" r="1.8" /><circle cx="8.5" cy="12" r="1.8" /></svg>
            <svg
              v-else-if="item.icon === 'flow'"
              class="h-4 w-4"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"
            ><rect x="2" y="2.5" width="4" height="3" rx="1" /><rect x="10" y="2.5" width="4" height="3" rx="1" /><rect x="6" y="10.5" width="4" height="3" rx="1" /><path d="M6 4h4M4 5.5v5M8 10.5v-4M12 5.5v5" /></svg>
            <svg
              v-else-if="item.icon === 'tpl'"
              class="h-4 w-4"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"
            ><path d="M3 2.5h7l3 3v8h-10z" /><path d="M10 2.5v3h3" /></svg>
            <svg
              v-else-if="item.icon === 'kb'"
              class="h-4 w-4"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"
            ><path d="M2 3.5h12v9H2z" /><path d="M5 3.5v9M5 7h9" /></svg>
            <svg
              v-else-if="item.icon === 'shield'"
              class="h-4 w-4"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"
            ><path d="M8 1.8l5 2v3.5c0 3.2-2 5.4-5 6.7-3-1.3-5-3.5-5-6.7v-3.5z" /><path d="M6 8l1.5 1.5L10.5 6" /></svg>
            <svg
              v-else
              class="h-4 w-4"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"
            ><path d="M2 13h12" /><path d="M3.5 13V8M7 13V5M10.5 13V3M14 13V9" /></svg>
            <span class="flex-1">{{ item.label }}</span>
            <span
              v-if="item.badge"
              class="font-mono text-[9px] tracking-wider text-teal"
              >{{ item.badge }}</span
            >
            <span v-else-if="item.soon" class="text-[9px] text-text-faint">待上线</span>
          </a>
        </div>
      </nav>

      <!-- 底部：主题 + 版本 -->
      <div class="border-t border-line px-4 py-4">
        <button
          type="button"
          class="mb-3 w-full rounded-md border border-line bg-panel-2 px-3 py-1.5 text-xs text-text-dim transition-colors hover:border-teal hover:text-text"
          @click="applyTheme(theme === 'dark' ? 'light' : 'dark')"
        >
          {{ theme === "dark" ? "☀ 切换亮色" : "🌙 切换暗色" }}
        </button>
        <div class="text-[11px] leading-relaxed text-text-faint">
          <div class="text-text-dim">演示环境</div>
          v0.9 · 单机部署
        </div>
      </div>
    </aside>

    <!-- ======== 内容区 ======== -->
    <main class="min-w-0 flex-1">
      <WebRtcSession v-if="view === 'chat'" />
      <ProviderConfigPanel v-else-if="view === 'config'" />
      <CallsPage v-else-if="view === 'records'" />
      <PersonasPage v-else-if="view === 'personas'" />
      <CustomersPage v-else-if="view === 'customers'" />
      <ScenesPage v-else-if="view === 'scenes'" @navigate="(v, s) => navigate(v, s)" />
      <ToolsPage v-else-if="view === 'tools'" :scene-id="pageScene" />
      <FlowEditorPage v-else-if="view === 'flow'" :scene-id="pageScene" />
      <TemplatesPage v-else-if="view === 'templates'" @navigate="(v, s) => navigate(v, s)" />
    </main>
  </div>
</template>
