import { translateRuntimeMessage } from "../../../../../i18n/runtimeLanguage";
import { base64ToBytes, standaloneHttpJson, type StandaloneHttpClient } from "../../httpClient";
import { normalizeVoiceLanguageCode } from "../../voiceLanguage";
import type { StandaloneTtsAdapter, StandaloneTtsInput } from "../types";

const QWEN_CLOUD_LANGUAGE_TYPES: Record<string, string> = {
  zh: "Chinese",
  en: "English",
  ja: "Japanese",
  ko: "Korean",
  yue: "Cantonese",
};

function resolveQwenCloudLanguageType(voiceLanguage?: string): string {
  const raw = String(voiceLanguage ?? "").trim();
  const normalized = normalizeVoiceLanguageCode(raw);
  if (normalized && normalized !== "auto") {
    return QWEN_CLOUD_LANGUAGE_TYPES[normalized] ?? raw;
  }
  return "Chinese";
}

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
  get label() {
    return translateRuntimeMessage("plat.standalone.tts.qwenLabel");
  },
  browserCors: "proxy-only",
  get description() {
    return translateRuntimeMessage("plat.standalone.tts.qwenDesc");
  },
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
      get label() {
        return translateRuntimeMessage("plat.standalone.tts.model");
      },
      type: "str",
      default: "qwen-tts",
    },
    default_voice_id: {
      get label() {
        return translateRuntimeMessage("plat.standalone.tts.qwenVoice");
      },
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
          language_type: resolveQwenCloudLanguageType(input.voiceLanguage),
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
