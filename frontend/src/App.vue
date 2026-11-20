<script setup lang="ts">
import AudioPlayer from "./components/AudioPlayer.vue";
import MicCapture from "./components/MicCapture.vue";
</script>

<template>
  <main class="app">
    <h1>callbot · 音频采集/播放测试页</h1>
    <p class="hint">
      WBS 2.1 交付物：浏览器麦克风采集与扬声器播放（WebRTC 信令与媒体通道在 2.2 接入）。
    </p>
    <MicCapture />
    <AudioPlayer />
  </main>
</template>
