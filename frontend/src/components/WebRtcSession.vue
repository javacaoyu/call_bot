<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { SignalingClient } from "../api/signaling";
import { computeAudioLevel } from "../utils/audio";

type ConnState = "idle" | "connecting" | "connected" | "error";
/** 会话四态：聆听 / 思考（AI 生成中）/ 播报（TTS 播放中） */
type TalkState = "idle" | "listening" | "thinking" | "speaking";

interface Bubble {
  role: "user" | "bot" | "mark";
  text: string;
}

const state = ref<ConnState>("idle");
const error = ref("");
const audioEl = ref<HTMLAudioElement | null>(null);
const devices = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref("");
const statusDetail = ref("");
const bubbles = ref<Bubble[]>([]);
const talkState = ref<TalkState>("idle");
const callSeconds = ref(0);
const interruptCount = ref(0);
const lastLatencyMs = ref<number | null>(null);
const waveLevel = ref(0);
const lines = ref({ asr: "—", tts: "—" });

const signaling = new SignalingClient();
let pc: RTCPeerConnection | null = null;
let localStream: MediaStream | null = null;
let audioCtx: AudioContext | null = null;
let processor: ScriptProcessorNode | null = null;
let playCtx: AudioContext | null = null;
let nextPlayTime = 0;
// 已调度的播放源：打断时立即停止（已排队未播 + 正在播的）
const activeSources: AudioBufferSourceNode[] = [];
// 播放确认：向后端报告最后播到的帧序号（打断窗口 = 前端播报中）
let lastAudioSeq = 0;
let audioQueued = false;
let callTimer: ReturnType<typeof setInterval> | null = null;
let utteranceAt = 0;

const SIGNAL_URL =
  (import.meta.env.VITE_SIGNAL_URL as string | undefined) ??
  "ws://localhost:8000/ws/signal";

const STATE_TEXT: Record<ConnState, string> = {
  idle: "未连接",
  connecting: "连接中…（等待媒体通道建立）",
  connected: "已连接（请说话，转写实时显示）",
  error: "出错",
};

const TALK_TEXT: Record<TalkState, string> = {
  idle: "待机",
  listening: "聆听中",
  thinking: "思考中",
  speaking: "播报中",
};

const callDuration = computed(() => {
  const m = Math.floor(callSeconds.value / 60);
  const s = callSeconds.value % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
});

const stateLampClass = computed(() => {
  switch (talkState.value) {
    case "listening":
      return "bg-green shadow-[0_0_10px_color-mix(in_srgb,var(--green)_50%,transparent)] animate-lamp";
    case "thinking":
      return "bg-blue animate-lamp [animation-duration:1.2s]";
    case "speaking":
      return "bg-teal shadow-[0_0_10px_color-mix(in_srgb,var(--teal)_60%,transparent)]";
    default:
      return "bg-text-faint";
  }
});

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

/** 波形柱高度：电平驱动 + 相位偏移（呼吸感）。 */
function waveHeight(n: number): number {
  const base = 5 + Math.sin((n / 28) * Math.PI * 2 + performance.now() / 260) * 3;
  return Math.max(4, Math.min(26, base + (waveLevel.value / 100) * 20));
}

/** 启动 PCM 直传：AudioContext 以 16k 单声道采集，二进制帧走信令 WS。 */
function startPcmStream(stream: MediaStream): void {
  audioCtx = new AudioContext({ sampleRate: 16000 });
  const source = audioCtx.createMediaStreamSource(stream);
  processor = audioCtx.createScriptProcessor(512, 1, 1); // 32ms@16k：降低打断帧边界延迟
  processor.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0);
    const buf = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      buf[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    waveLevel.value = computeAudioLevel(input);
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
  waveLevel.value = 0;
}

/** 播放后端 TTS 音频帧（base64 → AudioBuffer → 顺序调度）。 */
function playAudioFrame(data: string, sampleRate: number, seq: number): void {
  try {
    if (!playCtx) {
      playCtx = new AudioContext();
      nextPlayTime = 0;
    }
    lastAudioSeq = seq;
    audioQueued = true;
    const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
    const pcm = new Int16Array(bytes.buffer);
    const f32 = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) {
      f32[i] = pcm[i] / 32768;
    }
    const buffer = playCtx.createBuffer(1, f32.length, sampleRate);
    buffer.copyToChannel(f32, 0);
    const src = playCtx.createBufferSource();
    src.buffer = buffer;
    src.connect(playCtx.destination);
    const startAt = Math.max(nextPlayTime, playCtx.currentTime + 0.005);
    src.start(startAt);
    nextPlayTime = startAt + buffer.duration;
    activeSources.push(src);
    src.onended = () => {
      const i = activeSources.indexOf(src);
      if (i >= 0) activeSources.splice(i, 1);
      confirmPlaybackDone();
    };
  } catch {
    // 音频解码失败静默（不影响转写显示）
  }
}

/** 播放队列清空（自然播完或被 stop）后，向后端确认已播到的帧序号。 */
function confirmPlaybackDone(): void {
  if (activeSources.length === 0 && audioQueued) {
    audioQueued = false;
    signaling.send({ type: "playback_done", seq: lastAudioSeq });
    if (talkState.value === "speaking") talkState.value = "listening";
  }
}

/** 停止所有已调度/正在播的 TTS 音频（打断：计数+标记；静默：仅停播）。 */
function stopPlayback(markInterrupt: boolean): void {
  for (const src of activeSources) {
    try {
      src.stop();
    } catch {
      // 已结束的 source 忽略
    }
  }
  activeSources.length = 0;
  nextPlayTime = 0;
  if (markInterrupt) {
    interruptCount.value += 1;
    bubbles.value.push({ role: "mark", text: "客户打断" });
    talkState.value = "listening";
  }
  // stop 后 onended 同步触发 → confirmPlaybackDone 会发出确认；
  // 这里兜底再发一次（幂等，后端取 max）
  confirmPlaybackDone();
}

function startCallTimer(): void {
  stopCallTimer();
  callTimer = setInterval(() => {
    callSeconds.value += 1;
  }, 1000);
}

function stopCallTimer(): void {
  if (callTimer) {
    clearInterval(callTimer);
    callTimer = null;
  }
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
        talkState.value = "listening";
        callSeconds.value = 0;
        startCallTimer();
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
        // snapshot 语义（句级修订式 ASR）：替换当前用户气泡；增量式：追加
        const text = msg.text ?? "";
        if (!text) return;
        const last = bubbles.value[bubbles.value.length - 1];
        if (last && last.role === "user") {
          last.text = msg.snapshot ? text : last.text + text;
        } else {
          bubbles.value.push({ role: "user", text });
        }
        talkState.value = "listening";
      } else if (msg.type === "status") {
        statusDetail.value = msg.detail ?? "";
        parseLines(statusDetail.value);
      } else if (msg.type === "utterance") {
        // 完整转写确认：锁定用户气泡 + AI 开始思考
        const text = msg.text ?? "";
        const last = bubbles.value[bubbles.value.length - 1];
        if (last && last.role === "user") {
          last.text = text;
        } else {
          bubbles.value.push({ role: "user", text });
        }
        utteranceAt = performance.now();
        talkState.value = "thinking";
      } else if (msg.type === "reply") {
        if (utteranceAt) {
          lastLatencyMs.value = Math.round(performance.now() - utteranceAt);
          utteranceAt = 0;
        }
        const last = bubbles.value[bubbles.value.length - 1];
        if (last && last.role === "bot") {
          last.text += msg.text ?? "";
        } else {
          bubbles.value.push({ role: "bot", text: msg.text ?? "" });
        }
        talkState.value = "speaking";
      } else if (msg.type === "audio") {
        playAudioFrame(msg.data ?? "", msg.sample_rate ?? 24000, msg.seq ?? 0);
      } else if (msg.type === "stop_audio") {
        // 打断：立即停播（后端已清未发队列）
        stopPlayback(true);
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

function parseLines(detail: string): void {
  const m = detail.match(/ASR=(\S+) \/ TTS=(\S+)/);
  if (m) {
    lines.value = { asr: m[1], tts: m[2] };
  }
}

function disconnect(): void {
  stopPcmStream();
  stopPlayback(false); // 静默停止：不插打断标记不计数
  stopCallTimer();
  pc?.close();
  pc = null;
  localStream?.getTracks().forEach((t) => t.stop());
  localStream = null;
  signaling.close();
  statusDetail.value = "";
  bubbles.value = []; // 清空气泡（避免下次连接看到上轮的打断标记等残留）
  interruptCount.value = 0;
  lastLatencyMs.value = null;
  state.value = "idle";
  talkState.value = "idle";
}

onUnmounted(disconnect);
</script>

<template>
  <div class="mx-auto grid max-w-[1200px] grid-cols-1 gap-4 p-5 xl:grid-cols-[1fr_250px]">
    <!-- 左：通话区 -->
    <div class="min-w-0">
      <div class="overflow-hidden rounded-xl border border-line bg-panel transition-colors">
        <!-- 通话头 -->
        <div class="flex flex-wrap items-center gap-3.5 border-b border-line px-4.5 py-3.5">
          <span class="h-2.5 w-2.5 shrink-0 rounded-full" :class="stateLampClass"></span>
          <div class="min-w-[200px] flex-1">
            <div class="text-sm font-semibold">
              {{ TALK_TEXT[talkState] }}
              <span class="ml-2 font-mono text-[11px] text-text-faint"
                >ASR {{ lines.asr }} / TTS {{ lines.tts }}</span
              >
            </div>
            <div class="mt-0.5 text-[11px] text-text-dim">
              {{ statusDetail || STATE_TEXT[state] }}
            </div>
          </div>
          <div class="flex items-center gap-1.5">
            <select
              v-model="selectedDeviceId"
              class="max-w-[170px] rounded-md border border-line bg-panel-2 px-2 py-1.5 text-xs text-text"
              @change="disconnect"
            >
              <option v-for="d in devices" :key="d.deviceId" :value="d.deviceId">
                {{ d.label || `设备 ${d.deviceId.slice(0, 8)}` }}
              </option>
            </select>
            <button
              class="rounded-md border border-line bg-panel-2 px-3 py-1.5 text-xs text-text-dim transition-colors hover:border-teal hover:text-text"
              @click="refreshDevices"
            >
              刷新设备
            </button>
            <button
              class="rounded-md bg-teal px-3.5 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="state === 'connecting' || state === 'connected'"
              @click="connect"
            >
              连接
            </button>
            <button
              class="rounded-md border border-line bg-panel-2 px-3 py-1.5 text-xs text-text-dim transition-colors hover:border-red hover:text-red disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="state !== 'connected'"
              @click="disconnect"
            >
              断开
            </button>
          </div>
          <div class="text-right">
            <div class="font-mono text-xl font-semibold text-teal">{{ callDuration }}</div>
            <div class="text-[10px] tracking-[0.08em] text-text-faint">通话时长</div>
          </div>
        </div>

        <!-- 气泡流 -->
        <div class="flex min-h-[240px] max-h-[400px] flex-col gap-3 overflow-y-auto p-4.5">
          <p v-if="bubbles.length === 0" class="m-auto text-[13px] text-text-faint">
            连接后开始对话——你的语音转写与 AI 回复将在这里实时呈现
          </p>
          <div
            v-for="(b, i) in bubbles"
            :key="i"
            class="flex max-w-[82%]"
            :class="b.role === 'user' ? 'self-end' : 'self-start'"
          >
            <span
              v-if="b.role === 'mark'"
              class="self-center text-[11px] text-teal"
              >⚡ {{ b.text }}</span
            >
            <div
              v-else
              class="whitespace-pre-wrap rounded-[10px] border border-line bg-panel-2 px-3.5 py-2.5 text-[13px]"
              :class="
                b.role === 'bot'
                  ? 'rounded-tl-[3px] border-l-teal/40'
                  : 'rounded-tr-[3px] border-blue/40 bg-user-bubble'
              "
            >
              {{ b.text }}
            </div>
          </div>
        </div>

        <!-- 波形 -->
        <div class="flex items-center gap-2.5 border-t border-line bg-panel-2 px-4.5 py-2.5">
          <span class="whitespace-nowrap text-[10px] tracking-[0.1em] text-text-faint"
            >REC · 输入波形</span
          >
          <div class="flex h-[30px] flex-1 items-center gap-[3px] overflow-hidden">
            <span
              v-for="n in 28"
              :key="n"
              class="w-[3px] rounded-[2px] transition-[height] duration-100"
              :class="n % 2 ? 'bg-teal' : 'bg-blue'"
              :style="{ height: `${waveHeight(n)}px` }"
            ></span>
          </div>
        </div>

        <p v-if="error" class="px-4.5 pb-2.5 text-xs text-red">{{ error }}</p>
        <audio ref="audioEl" autoplay></audio>
      </div>
    </div>

    <!-- 右：统计侧栏 -->
    <div class="flex flex-col gap-3">
      <div class="rounded-xl border border-line bg-panel p-3.5 transition-colors">
        <div class="text-[10px] tracking-[0.1em] text-text-faint">本轮延迟</div>
        <div class="mt-1 font-mono text-[22px] font-bold">
          {{ lastLatencyMs !== null ? lastLatencyMs : "—" }}<span
            v-if="lastLatencyMs !== null"
            class="ml-1 text-[11px] font-normal text-text-dim"
            >ms</span
          >
        </div>
        <div class="mt-1 text-[11px] text-text-dim">首字响应（目标 &lt;500ms）</div>
      </div>
      <div class="rounded-xl border border-line bg-panel p-3.5 transition-colors">
        <div class="text-[10px] tracking-[0.1em] text-text-faint">打断次数</div>
        <div class="mt-1 font-mono text-[22px] font-bold">
          {{ interruptCount }}<span class="ml-1 text-[11px] font-normal text-text-dim">次</span>
        </div>
        <div class="mt-1 text-[11px] text-text-dim">开口即停 · 全双工</div>
      </div>
      <div class="rounded-xl border border-line bg-panel p-3.5 transition-colors">
        <div class="text-[10px] tracking-[0.1em] text-text-faint">模型走线</div>
        <div class="mt-2 flex flex-col gap-1.5 text-xs">
          <span class="flex items-center gap-1.5"
            ><i class="inline-block h-1.75 w-1.75 rounded-full bg-blue"></i>识别 ·
            {{ lines.asr }}</span
          >
          <span class="flex items-center gap-1.5"
            ><i class="inline-block h-1.75 w-1.75 rounded-full bg-blue"></i>合成 ·
            {{ lines.tts }}</span
          >
          <span class="flex items-center gap-1.5"
            ><i class="inline-block h-1.75 w-1.75 rounded-full bg-teal"></i>编排 ·
            AgentScope</span
          >
        </div>
      </div>
    </div>
  </div>
</template>
