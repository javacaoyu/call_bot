<script setup lang="ts">
import { onUnmounted, ref } from "vue";
import { SignalingClient } from "../api/signaling";

type ConnState = "idle" | "connecting" | "connected" | "error";

const state = ref<ConnState>("idle");
const error = ref("");
const audioEl = ref<HTMLAudioElement | null>(null);
const devices = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref("");
const transcript = ref("");
const statusDetail = ref("");

const signaling = new SignalingClient();
let pc: RTCPeerConnection | null = null;
let localStream: MediaStream | null = null;
let audioCtx: AudioContext | null = null;
let processor: ScriptProcessorNode | null = null;

const SIGNAL_URL =
  (import.meta.env.VITE_SIGNAL_URL as string | undefined) ??
  "ws://localhost:8000/ws/signal";

const STATE_TEXT: Record<ConnState, string> = {
  idle: "未连接",
  connecting: "连接中…（等待媒体通道建立）",
  connected: "已连接（请说话，转写实时显示）",
  error: "出错",
};

function pickDefault(devs: MediaDeviceInfo[]): string {
  // 优先真实麦克风（排除虚拟设备，如 LegionZone 虚拟麦克风）
  const real = devs.find(
    (d) =>
      /麦克风|microphone|mic/i.test(d.label) && !/虚拟|virtual|legion/i.test(d.label),
  );
  return real?.deviceId ?? devs[0]?.deviceId ?? "";
}

async function refreshDevices(): Promise<void> {
  devices.value = (await navigator.mediaDevices.enumerateDevices()).filter(
    (d) => d.kind === "audioinput",
  );
  if (!devices.value.some((d) => d.deviceId === selectedDeviceId.value)) {
    selectedDeviceId.value = pickDefault(devices.value);
  }
}

/** 启动 PCM 直传：AudioContext 以 16k 单声道采集，二进制帧走信令 WS。 */
function startPcmStream(stream: MediaStream): void {
  audioCtx = new AudioContext({ sampleRate: 16000 });
  const source = audioCtx.createMediaStreamSource(stream);
  processor = audioCtx.createScriptProcessor(1024, 1, 1);
  processor.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0);
    const buf = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      buf[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    signaling.sendBinary(buf.buffer);
  };
  source.connect(processor);
  // ScriptProcessor 需连接到 destination 才会触发回调；经零增益节点避免自听
  const mute = audioCtx.createGain();
  mute.gain.value = 0;
  processor.connect(mute);
  mute.connect(audioCtx.destination);
}

function stopPcmStream(): void {
  processor?.disconnect();
  processor = null;
  audioCtx?.close();
  audioCtx = null;
}

async function connect(): Promise<void> {
  state.value = "connecting";
  error.value = "";
  try {
    await signaling.connect(SIGNAL_URL);
    localStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        ...(selectedDeviceId.value
          ? { deviceId: { exact: selectedDeviceId.value } }
          : {}),
      },
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
      } else if (msg.type === "transcript") {
        transcript.value += msg.text ?? "";
      } else if (msg.type === "status") {
        statusDetail.value = msg.detail ?? "";
      }
    });
    signaling.onClose(() => {
      if (state.value !== "idle") {
        error.value = "信令连接已断开";
        state.value = "error";
      }
    });

    startPcmStream(localStream);

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    signaling.send({ type: "offer", sdp: offer.sdp });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
    state.value = "error";
  }
}

function disconnect(): void {
  stopPcmStream();
  pc?.close();
  pc = null;
  localStream?.getTracks().forEach((t) => t.stop());
  localStream = null;
  signaling.close();
  transcript.value = "";
  statusDetail.value = "";
  state.value = "idle";
}

onUnmounted(disconnect);
</script>

<template>
  <section class="card">
    <h2>WebRTC 实时语音转写（流式 ASR）</h2>
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
    <p v-if="statusDetail" class="status">⏳ {{ statusDetail }}</p>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="transcript">
      <div class="transcript-label">实时转写（流式 ASR）</div>
      <div class="transcript-text">{{ transcript || "（连接后请说话）" }}</div>
    </div>
    <audio ref="audioEl" autoplay></audio>
  </section>
</template>

<style scoped>
.transcript {
  margin-top: 12px;
  padding: 12px;
  background: #f0f9ff;
  border-radius: 6px;
  min-height: 60px;
}

.transcript-label {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 4px;
}

.transcript-text {
  font-size: 16px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
