import type { StandaloneTtsAdapter, StandaloneTtsInput } from "../types";

export const browserSpeechTtsAdapter: StandaloneTtsAdapter = {
  id: "browser-speech",
  label: "浏览器系统朗读 (免 Key 轻量兜底)",
  browserCors: "supported",
  description: "调用当前设备系统内置语音朗读台词，无需任何 API Key（不支持口型音频波纹采样）。",
  schema: {
    rate: {
      label: "语速倍率",
      type: "float",
      min: 0.5,
      max: 2.0,
      step: 0.1,
      default: 1.0,
    },
    pitch: {
      label: "音高倍率",
      type: "float",
      min: 0.5,
      max: 2.0,
      step: 0.1,
      default: 1.0,
    },
  },
  async synthesize(input: StandaloneTtsInput, extra: Record<string, unknown>): Promise<Blob | null> {
    if (
      typeof window === "undefined" ||
      !("speechSynthesis" in window) ||
      typeof SpeechSynthesisUtterance === "undefined"
    ) {
      return null;
    }
    const text = input.text.trim();
    if (!text) return null;

    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = typeof extra.rate === "number" ? extra.rate : (input.speed ?? 1.0);
      utterance.pitch = typeof extra.pitch === "number" ? extra.pitch : 1.0;
      utterance.volume = Math.min(1, Math.max(0, input.volume ?? 1.0));
      utterance.lang = input.voiceLanguage === "ja" ? "ja-JP" : input.voiceLanguage === "en" ? "en-US" : "zh-CN";
      window.speechSynthesis.speak(utterance);
    } catch {
      // Ignore synthesis availability issues in headless/iframe environments
    }
    return null;
  },
};
