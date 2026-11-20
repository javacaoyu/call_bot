<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { computeAudioLevel } from "../utils/audio";

const devices = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref("");
const stream = ref<MediaStream | null>(null);
const level = ref(0);
const error = ref("");
const ctxState = ref("");
const trackInfo = ref("");

let audioCtx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let rafId = 0;

const running = computed(() => stream.value !== null);

async function refreshDevices(): Promise<void> {
  devices.value = (await navigator.mediaDevices.enumerateDevices()).filter(
    (d) => d.kind === "audioinput",
  );
  // 当前选择已失效（授权后 deviceId 可能变化）时回退到第一台设备
  if (!devices.value.some((d) => d.deviceId === selectedDeviceId.value)) {
    selectedDeviceId.value = devices.value[0]?.deviceId ?? "";
  }
}

async function start(): Promise<void> {
  error.value = "";
  try {
    stream.value = await navigator.mediaDevices.getUserMedia({
      // exact 强制使用所选设备（软约束会被 Chrome 无视）
      audio: selectedDeviceId.value
        ? { deviceId: { exact: selectedDeviceId.value } }
        : true,
    });
    const track = stream.value.getAudioTracks()[0];
    trackInfo.value = track
      ? `${track.label || "未命名设备"}${track.muted ? "（已静音）" : ""}`
      : "无音轨";

    // 授权后重新枚举，拿到真实 deviceId 与设备名
    await refreshDevices();

    audioCtx = new AudioContext();
    // 修复浏览器自动播放策略：挂起的 AudioContext 收不到任何数据
    if (audioCtx.state === "suspended") {
      await audioCtx.resume();
    }
    ctxState.value = audioCtx.state;

    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    const source = audioCtx.createMediaStreamSource(stream.value);
    source.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    const loop = (): void => {
      if (analyser) {
        analyser.getFloatTimeDomainData(buf);
        level.value = computeAudioLevel(buf);
      }
      rafId = requestAnimationFrame(loop);
    };
    loop();
  } catch (e) {
    // exact 约束失效时自动刷新设备列表，提示重新选择
    await refreshDevices();
    error.value = `采集失败：${
      e instanceof Error ? e.message : String(e)
    }（设备列表已刷新，请重新选择后重试）`;
  }
}

function stop(): void {
  cancelAnimationFrame(rafId);
  stream.value?.getTracks().forEach((t) => t.stop());
  stream.value = null;
  audioCtx?.close();
  audioCtx = null;
  analyser = null;
  level.value = 0;
  ctxState.value = "";
  trackInfo.value = "";
}

onUnmounted(stop);
</script>

<template>
  <section class="card">
    <h2>麦克风采集</h2>
    <select v-model="selectedDeviceId" @change="stop">
      <option v-for="d in devices" :key="d.deviceId" :value="d.deviceId">
        {{ d.label || `设备 ${d.deviceId.slice(0, 8)}` }}
      </option>
    </select>
    <button @click="refreshDevices">刷新设备</button>
    <button :disabled="running" @click="start">开始采集</button>
    <button :disabled="!running" @click="stop">停止</button>
    <div class="meter">
      <div class="meter-bar" :style="{ width: `${level}%` }"></div>
    </div>
    <p class="status">
      {{
        running
          ? `采集中（音量 ${level.toFixed(0)} | 设备：${trackInfo} | ctx：${ctxState}）`
          : "未采集"
      }}
    </p>
    <p v-if="running && ctxState !== '' && ctxState !== 'running'" class="error">
      AudioContext 状态异常（{{ ctxState }}）：请检查浏览器权限或换设备重试
    </p>
    <p v-if="error" class="error">{{ error }}</p>
  </section>
</template>

<style scoped>
.meter {
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  margin-top: 12px;
}

.meter-bar {
  height: 100%;
  background: #22c55e;
  border-radius: 4px;
  transition: width 80ms linear;
}
</style>
