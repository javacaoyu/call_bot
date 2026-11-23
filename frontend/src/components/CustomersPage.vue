<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  createCustomer,
  deleteCustomer,
  fetchCustomers,
  updateCustomer,
  type Customer,
} from "../api/customers";

const customers = ref<Customer[]>([]);
const loading = ref(true);
const error = ref("");
const saved = ref("");
const showEditor = ref(false);
const editing = ref<Customer | null>(null);
const form = reactive({ name: "", phone: "", notes: "" });

function openEditor(c: Customer | null): void {
  editing.value = c;
  form.name = c?.name ?? "";
  form.phone = c?.phone ?? "";
  form.notes = c?.notes ?? "";
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
    customers.value = await fetchCustomers();
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
      await updateCustomer(editing.value.id, { ...form });
      saved.value = "已保存";
    } else {
      await createCustomer({ ...form });
      saved.value = "已创建";
    }
    closeEditor();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function remove(c: Customer): Promise<void> {
  error.value = "";
  if (!window.confirm(`删除客户「${c.name}」？`)) return;
  try {
    await deleteCustomer(c.id);
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
        <h2 class="text-xl font-semibold">客户管理</h2>
        <p class="mt-1 text-xs text-text-dim">外呼客户信息维护——工作台外呼前从本表选择客户</p>
      </div>
      <button
        class="rounded-md bg-teal px-3.5 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
        @click="openEditor(null)"
      >
        + 新建客户
      </button>
    </div>

    <p v-if="error" class="mb-3 text-xs text-red">{{ error }}</p>
    <p v-if="saved" class="mb-3 text-xs text-teal">{{ saved }}</p>
    <p v-if="loading" class="text-[13px] text-text-dim">读取中…</p>

    <!-- 编辑器 -->
    <div v-if="showEditor" class="mb-4 rounded-xl border border-line bg-panel p-5 transition-colors">
      <h3 class="mb-3 text-sm font-semibold">{{ editing ? `编辑 · ${editing.name}` : "新建客户" }}</h3>
      <div class="flex flex-col gap-3">
        <div class="grid grid-cols-2 gap-3">
          <label class="flex flex-col gap-1 text-xs text-text-dim">
            姓名
            <input v-model="form.name" placeholder="客户姓名" class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-text-dim">
            电话
            <input v-model="form.phone" placeholder="11 位手机号" class="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-text outline-none focus:border-blue" />
          </label>
        </div>
        <label class="flex flex-col gap-1 text-xs text-text-dim">
          备注
          <input v-model="form.notes" placeholder="如：理财回访场景客户" class="rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-blue" />
        </label>
        <div class="flex gap-2">
          <button
            class="rounded-md bg-teal px-4 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            :disabled="!form.name || !form.phone"
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
      <div class="grid grid-cols-[1.2fr_1.2fr_1.6fr_0.6fr] gap-3 border-b border-line px-4 py-2.5 text-[10px] tracking-[0.08em] text-text-faint">
        <span>姓名</span><span>电话</span><span>备注</span><span></span>
      </div>
      <div
        v-for="c in customers"
        :key="c.id"
        class="grid grid-cols-[1.2fr_1.2fr_1.6fr_0.6fr] items-center gap-3 border-b border-line px-4 py-3 text-[12.5px] last:border-b-0"
      >
        <span class="font-medium">{{ c.name }}</span>
        <span class="font-mono text-text-dim">{{ c.phone }}</span>
        <span class="truncate text-text-dim">{{ c.notes || "—" }}</span>
        <span class="flex justify-end gap-2">
          <button
            class="rounded-md border border-line bg-panel-2 px-2.5 py-1 text-[11px] text-text-dim transition-colors hover:text-text"
            @click="openEditor(c)"
          >
            编辑
          </button>
          <button
            class="rounded-md border border-line bg-panel-2 px-2.5 py-1 text-[11px] text-text-dim transition-colors hover:border-red hover:text-red"
            @click="remove(c)"
          >
            删除
          </button>
        </span>
      </div>
      <p v-if="!loading && customers.length === 0" class="py-10 text-center text-[13px] text-text-faint">
        暂无客户——点击右上角新建
      </p>
    </div>
  </div>
</template>
