import { base64ToBytes, standaloneHttpJson, type StandaloneHttpClient } from "../../httpClient";
import type { StandaloneTtsAdapter, StandaloneTtsInput } from "../types";

interface QwenTtsResponse {
  output?: {
    audio?: {
      url?: string;
      data?: string;
    };
  };
}

export const qwenTtsAdapter: StandaloneTtsAdapter = {
  id: "qwen-tts",
  label: "阿里百炼 Qwen TTS (手机端原生免跨域直连)",
  browserCors: "proxy-only",
  description: "DashScope 通义千问语音合成，手机 App 通过原生 HTTP 直连无跨域限制；网页端需配 CORS 代理。",
  schema: {
    api_key: {
      label: "DashScope API Key",
      type: "str",
      secret: true,
      default: "",
    },
    base_api_url: {
      label: "DashScope Endpoint",
      type: "str",
      default: "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    },
    model: {
      label: "模型",
      type: "str",
      default: "qwen-tts",
    },
    default_voice_id: {
      label: "默认音色 (如 Cherry / Chelsie / Ethan)",
      type: "str",
      default: "Cherry",
    },
  },
  async synthesize(
    input: StandaloneTtsInput,
    extra: Record<string, unknown>,
    http: StandaloneHttpClient,
  ): Promise<Blob | null> {
    const apiKey = typeof extra.api_key === "string" ? extra.api_key.trim() : "";
    const text = input.text.trim();
    if (!apiKey || !text) return null;

    const endpoint =
      typeof extra.base_api_url === "string" && extra.base_api_url.trim()
        ? extra.base_api_url.trim()
        : "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation";
    const model = typeof extra.model === "string" && extra.model.trim() ? extra.model.trim() : "qwen-tts";
    const voice =
      typeof extra.default_voice_id === "string" && extra.default_voice_id.trim()
        ? extra.default_voice_id.trim()
        : "Cherry";

    const { data } = await standaloneHttpJson<QwenTtsResponse>({
      url: endpoint,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        input: {
          text,
          voice,
          language_type: input.voiceLanguage || "Chinese",
        },
      }),
      timeoutMs: 45_000,
      signal: input.signal,
    });

    if (data.output?.audio?.data) {
      const bytes = base64ToBytes(data.output.audio.data);
      const copy = new Uint8Array(bytes.byteLength);
      copy.set(bytes);
      return new Blob([copy], { type: "audio/wav" });
    }
    if (data.output?.audio?.url) {
      const audioResp = await http({
        url: data.output.audio.url,
        method: "GET",
        timeoutMs: 30_000,
        signal: input.signal,
      });
      if (audioResp.ok && audioResp.body.byteLength > 64) {
        const copy = new Uint8Array(audioResp.body.byteLength);
        copy.set(audioResp.body);
        const mime = audioResp.headers["content-type"]?.split(";")[0]?.trim() || "audio/wav";
        return new Blob([copy], { type: mime });
      }
    }
    return null;
  },
};
