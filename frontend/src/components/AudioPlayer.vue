<script setup lang="ts">
import { ref } from "vue";

const playing = ref(false);
const error = ref("");

let audioCtx: AudioContext | null = null;

function playTestTone(): void {
  error.value = "";
  try {
    audioCtx = new AudioContext();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    gain.gain.value = 0.1;
    osc.frequency.value = 440;
    osc.connect(gain).connect(audioCtx.destination);
    osc.start();
    playing.value = true;
    window.setTimeout(() => {
      osc.stop();
      audioCtx?.close();
      audioCtx = null;
      playing.value = false;
    }, 1000);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}
</script>

<template>
  <section class="card">
    <h2>扬声器播放</h2>
    <button :disabled="playing" @click="playTestTone">播放测试音</button>
    <p class="status">
      {{ playing ? "播放中…" : "空闲（TTS 音频流在后续阶段接入）" }}
    </p>
    <p v-if="error" class="error">{{ error }}</p>
  </section>
</template>
