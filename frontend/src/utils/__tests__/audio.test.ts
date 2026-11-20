import { describe, expect, it } from "vitest";
import { computeAudioLevel } from "../audio";

describe("computeAudioLevel", () => {
  it("静音帧返回 0", () => {
    expect(computeAudioLevel(new Float32Array(1024))).toBe(0);
  });

  it("满幅正弦波返回 100", () => {
    const samples = new Float32Array(1024);
    for (let i = 0; i < samples.length; i++) {
      samples[i] = Math.sin((2 * Math.PI * i) / 32);
    }
    expect(computeAudioLevel(samples)).toBe(100);
  });

  it("空数组返回 0", () => {
    expect(computeAudioLevel(new Float32Array(0))).toBe(0);
  });
});
