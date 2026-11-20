<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { computeAudioLevel } from "../utils/audio";

const devices = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref("");
const stream = ref<MediaStream | null>(null);
const level = ref(0);
const error = ref("");

let audioCtx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let rafId = 0;

const running = computed(() => stream.value !== null);

async function refreshDevices(): Promise<void> {
  devices.value = (await navigator.mediaDevices.enumerateDevices()).filter(
    (d) => d.kind === "audioinput",
  );
  if (!selectedDeviceId.value && devices.value.length > 0) {
    selectedDeviceId.value = devices.value[0].deviceId;
  }
}

async function start(): Promise<void> {
  error.value = "";
  try {
    stream.value = await navigator.mediaDevices.getUserMedia({
      audio: selectedDeviceId.value ? { deviceId: selectedDeviceId.value } : true,
    });
    audioCtx = new AudioContext();
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
    error.value = e instanceof Error ? e.message : String(e);
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
    <p class="status">{{ running ? `采集中（音量 ${level.toFixed(0)}）` : "未采集" }}</p>
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
