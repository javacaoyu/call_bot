<script setup lang="ts">
import { ref } from "vue";
import ProviderConfigPanel from "./components/ProviderConfigPanel.vue";
import WebRtcSession from "./components/WebRtcSession.vue";

const view = ref<"chat" | "config">("chat");
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="brand-lamp" aria-hidden="true"></span>
        <span class="brand-name">callbot</span>
        <span class="brand-sub">外呼语音引擎</span>
      </div>
      <nav class="tabs" aria-label="页面导航">
        <button
          type="button"
          :class="{ active: view === 'chat' }"
          @click="view = 'chat'"
        >
          对话测试
        </button>
        <button
          type="button"
          :class="{ active: view === 'config' }"
          @click="view = 'config'"
        >
          线路配置
        </button>
      </nav>
    </header>
    <main class="content">
      <WebRtcSession v-if="view === 'chat'" />
      <ProviderConfigPanel v-else />
    </main>
  </div>
</template>
