<script setup lang="ts">
import { onUnmounted, ref } from "vue";
import { SignalingClient } from "../api/signaling";

type ConnState = "idle" | "connecting" | "connected" | "error";

const state = ref<ConnState>("idle");
const error = ref("");
const audioEl = ref<HTMLAudioElement | null>(null);
const devices = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref("");

const signaling = new SignalingClient();
let pc: RTCPeerConnection | null = null;
let localStream: MediaStream | null = null;

const SIGNAL_URL =
  (import.meta.env.VITE_SIGNAL_URL as string | undefined) ??
  "ws://localhost:8000/ws/signal";

const STATE_TEXT: Record<ConnState, string> = {
  idle: "未连接",
  connecting: "连接中…（等待媒体通道建立）",
  connected: "已连接（说话应听到回声）",
  error: "出错",
};

async function refreshDevices(): Promise<void> {
  devices.value = (await navigator.mediaDevices.enumerateDevices()).filter(
    (d) => d.kind === "audioinput",
  );
  if (!devices.value.some((d) => d.deviceId === selectedDeviceId.value)) {
    selectedDeviceId.value = devices.value[0]?.deviceId ?? "";
  }
}

async function connect(): Promise<void> {
  state.value = "connecting";
  error.value = "";
  try {
    await signaling.connect(SIGNAL_URL);
    localStream = await navigator.mediaDevices.getUserMedia({
      audio: selectedDeviceId.value
        ? { deviceId: { exact: selectedDeviceId.value } }
        : true,
    });
    await refreshDevices();

    pc = new RTCPeerConnection();
    localStream.getTracks().forEach((t) => pc!.addTrack(t, localStream!));

    pc.onicecandidate = (e) => {
      if (e.candidate) {
        signaling.send({ type: "ice", candidate: e.candidate.toJSON() });
      }
    };
    pc.ontrack = (e) => {
      if (audioEl.value) {
        audioEl.value.srcObject = e.streams[0];
      }
    };
    // 真实连接状态：只有 media 通道建立才算已连接
    pc.onconnectionstatechange = () => {
      if (pc?.connectionState === "connected") {
        state.value = "connected";
      } else if (pc?.connectionState === "failed") {
        error.value = "媒体通道建立失败";
        state.value = "error";
      }
    };

    signaling.onMessage(async (msg) => {
      if (msg.type === "answer" && msg.sdp && pc) {
        await pc.setRemoteDescription({ type: "answer", sdp: msg.sdp });
      } else if (msg.type === "ice" && msg.candidate && pc) {
        await pc.addIceCandidate(msg.candidate);
      } else if (msg.type === "error") {
        error.value = msg.detail ?? "信令错误";
        state.value = "error";
      }
    });
    signaling.onClose(() => {
      if (state.value !== "idle") {
        error.value = "信令连接已断开";
        state.value = "error";
      }
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    signaling.send({ type: "offer", sdp: offer.sdp });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
    state.value = "error";
  }
}

function disconnect(): void {
  pc?.close();
  pc = null;
  localStream?.getTracks().forEach((t) => t.stop());
  localStream = null;
  signaling.close();
  state.value = "idle";
}

onUnmounted(disconnect);
</script>

<template>
  <section class="card">
    <h2>WebRTC 媒体通道（回声环回验证）</h2>
    <select v-model="selectedDeviceId" @change="disconnect">
      <option v-for="d in devices" :key="d.deviceId" :value="d.deviceId">
        {{ d.label || `设备 ${d.deviceId.slice(0, 8)}` }}
      </option>
    </select>
    <button @click="refreshDevices">刷新设备</button>
    <button :disabled="state === 'connecting' || state === 'connected'" @click="connect">
      连接
    </button>
    <button :disabled="state !== 'connected'" @click="disconnect">断开</button>
    <p class="status">{{ STATE_TEXT[state] }}</p>
    <p v-if="error" class="error">{{ error }}</p>
    <audio ref="audioEl" autoplay></audio>
  </section>
</template>
