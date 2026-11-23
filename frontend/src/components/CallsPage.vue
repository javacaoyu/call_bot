<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchCalls, type CallRecord } from "../api/calls";

const calls = ref<CallRecord[]>([]);
const loading = ref(true);
const error = ref("");
const expandedId = ref<string | null>(null);

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function fmtDuration(s: number): string {
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

const statusClass = computed(() => (status: string) => {
  switch (status) {
    case "connected":
      return "border-green/45 text-green";
    case "no_answer":
      return "border-teal/45 text-teal";
    default:
      return "border-red/45 text-red";
  }
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    calls.value = await fetchCalls();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="mx-auto max-w-[1000px] p-5">
    <div class="mb-4 flex items-center justify-between">
      <div>
        <h2 class="text-xl font-semibold">通话记录</h2>
        <p class="mt-1 text-xs text-text-dim">全程转写留存 · 点击行查看对话详情</p>
      </div>
      <button
        class="rounded-md border border-line bg-panel-2 px-3.5 py-1.5 text-xs text-text-dim transition-colors hover:border-teal hover:text-text"
        :disabled="loading"
        @click="load"
      >
        {{ loading ? "读取中…" : "刷新" }}
      </button>
    </div>

    <p v-if="error" class="mb-3 text-xs text-red">{{ error }}</p>
    <p v-if="!loading && calls.length === 0" class="py-16 text-center text-[13px] text-text-faint">
      暂无通话记录——去对话工作台聊几句再回来
    </p>

    <div class="overflow-hidden rounded-xl border border-line bg-panel transition-colors">
      <div class="grid grid-cols-[1.2fr_0.6fr_0.6fr_1fr_0.6fr] gap-3 border-b border-line px-4 py-2.5 text-[10px] tracking-[0.08em] text-text-faint">
        <span>时间</span><span>结果</span><span>时长</span><span>打断</span><span></span>
      </div>
      <template v-for="c in calls" :key="c.id">
        <button
          type="button"
          class="grid w-full grid-cols-[1.2fr_0.6fr_0.6fr_1fr_0.6fr] items-center gap-3 border-b border-line px-4 py-3 text-left text-[12.5px] transition-colors last:border-b-0 hover:bg-panel-2"
          @click="expandedId = expandedId === c.id ? null : c.id"
        >
          <span class="font-mono text-text-dim">{{ fmtDate(c.started_at) }} {{ fmtTime(c.started_at) }}</span>
          <span class="inline-flex w-fit items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]" :class="statusClass(c.status)">
            {{ c.status_text }}
          </span>
          <span class="font-mono text-text-dim">{{ fmtDuration(c.duration_s) }}</span>
          <span class="font-mono text-text-dim">{{ c.interrupt_count }} 次</span>
          <span class="text-right text-[11px] text-teal">{{ expandedId === c.id ? "收起 ▲" : "详情 ▼" }}</span>
        </button>
        <div v-if="expandedId === c.id" class="border-b border-line bg-panel-2 px-5 py-4">
          <div class="flex max-w-[85%] flex-col gap-3">
            <div
              v-for="(b, i) in c.transcript"
              :key="i"
              class="flex"
              :class="b.role === 'user' ? 'self-end' : 'self-start'"
            >
              <span v-if="b.role === 'mark'" class="self-center text-[11px] text-teal">⚡ {{ b.text }}</span>
              <div
                v-else
                class="whitespace-pre-wrap rounded-lg border border-line bg-panel px-3 py-2 text-[13px]"
                :class="b.role === 'bot' ? 'rounded-tl-[3px] border-l-teal/40' : 'rounded-tr-[3px] border-blue/40 bg-user-bubble'"
              >
                {{ b.text }}
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
