/** 计算音频帧的音量等级（0-100）。 */
export function computeAudioLevel(samples: Float32Array): number {
  if (samples.length === 0) {
    return 0;
  }
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    sum += samples[i] * samples[i];
  }
  const rms = Math.sqrt(sum / samples.length);
  // RMS 0.1 视为满格，映射到 0-100 并截断
  return Math.min(100, Math.round((rms / 0.1) * 100));
}
