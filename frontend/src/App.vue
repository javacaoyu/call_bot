<script setup lang="ts">
import AudioPlayer from "./components/AudioPlayer.vue";
import MicCapture from "./components/MicCapture.vue";
import WebRtcSession from "./components/WebRtcSession.vue";
</script>

<template>
  <main class="app">
    <h1>callbot · 音频采集/播放测试页</h1>
    <p class="hint">
      WBS 2.1 交付物：麦克风采集与扬声器播放。WBS 2.2：WebRTC 媒体通道（回声环回验证）。
    </p>
    <MicCapture />
    <AudioPlayer />
    <WebRtcSession />
  </main>
</template>
