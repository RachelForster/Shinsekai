import { bytesToBase64, type StandaloneHttpClient } from "../../httpClient";
import type { StandaloneTtsAdapter, StandaloneTtsInput } from "../types";

async function readBlobBytes(blob: Blob): Promise<Uint8Array> {
  if (typeof blob.arrayBuffer === "function") {
    return new Uint8Array(await blob.arrayBuffer());
  }
  if (typeof FileReader !== "undefined") {
    return new Promise<Uint8Array>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
      reader.onerror = () => reject(reader.error ?? new Error("Failed to read Blob"));
      reader.readAsArrayBuffer(blob);
    });
  }
  if (typeof Response !== "undefined") {
    return new Uint8Array(await new Response(blob).arrayBuffer());
  }
  throw new Error("Failed to read audio reference Blob");
}

async function blobToDataUri(blob: Blob): Promise<string> {
  const bytes = await readBlobBytes(blob);
  const mime = blob.type || "audio/wav";
  return `data:${mime};base64,${bytesToBase64(bytes)}`;
}

function toSafeBlob(bytes: Uint8Array, mimeType: string): Blob {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return new Blob([copy], { type: mimeType });
}

function resolveApiKey(input: StandaloneTtsInput, extra: Record<string, unknown>): string {
  const explicitKey = typeof extra.api_key === "string" ? extra.api_key.trim() : "";
  if (explicitKey) return explicitKey;

  const reuseLlmKey = extra.reuse_llm_key !== false;
  if (!reuseLlmKey) return "";

  const keys = input.apiConfig.llm_api_key ?? {};
  const siliconKey = typeof keys["硅基流动"] === "string" ? keys["硅基流动"].trim() : "";
  const activeKey =
    typeof keys[input.apiConfig.llm_provider] === "string"
      ? keys[input.apiConfig.llm_provider].trim()
      : "";
  return siliconKey || activeKey;
}

export const openaiSpeechTtsAdapter: StandaloneTtsAdapter = {
  id: "openai-speech",
  label: "OpenAI 兼容语音 (硅基流动 CosyVoice2 · 支持一Key复用)",
  browserCors: "supported",
  description:
    "兼容 OpenAI /v1/audio/speech，默认指向硅基流动 CosyVoice2；勾选复用 Key 后可直接共用对话 Key。",
  schema: {
    reuse_llm_key: {
      label: "复用对话 LLM Key（硅基流动等同源服务可直接留空语音 Key）",
      type: "bool",
      default: true,
    },
    api_key: {
      label: "语音 API Key（若未勾选复用则必填）",
      type: "str",
      secret: true,
      default: "",
    },
    base_api_url: {
      label: "Speech Base URL",
      type: "str",
      default: "https://api.siliconflow.cn/v1",
    },
    model: {
      label: "语音模型 ID",
      type: "str",
      default: "FunAudioLLM/CosyVoice2-0.5B",
    },
    default_voice_id: {
      label: "默认音色 Voice ID",
      type: "str",
      default: "FunAudioLLM/CosyVoice2-0.5B:claire",
    },
    enable_zero_shot: {
      label: "若角色有参考音频，尝试零样本音色克隆",
      type: "bool",
      default: true,
    },
    response_format: {
      label: "音频格式",
      type: "str",
      choices: ["mp3", "wav", "opus"],
      default: "mp3",
    },
  },
  async synthesize(
    input: StandaloneTtsInput,
    extra: Record<string, unknown>,
    http: StandaloneHttpClient,
  ): Promise<Blob | null> {
    const text = input.text.trim();
    if (!text) return null;

    const apiKey = resolveApiKey(input, extra);
    if (!apiKey) {
      return null;
    }

    const baseUrl = (
      typeof extra.base_api_url === "string" && extra.base_api_url.trim()
        ? extra.base_api_url.trim()
        : "https://api.siliconflow.cn/v1"
    )
      .replace(/\/+$/, "")
      .replace(/\/audio\/speech$/i, "");

    const model =
      typeof extra.model === "string" && extra.model.trim()
        ? extra.model.trim()
        : "FunAudioLLM/CosyVoice2-0.5B";
    const voice =
      typeof extra.default_voice_id === "string" && extra.default_voice_id.trim()
        ? extra.default_voice_id.trim()
        : "FunAudioLLM/CosyVoice2-0.5B:claire";
    const responseFormat =
      typeof extra.response_format === "string" && extra.response_format.trim()
        ? extra.response_format.trim()
        : "mp3";
    const speed =
      typeof input.speed === "number" && Number.isFinite(input.speed)
        ? Math.min(2, Math.max(0.5, input.speed))
        : 1.0;

    const enableZeroShot = extra.enable_zero_shot !== false;
    const isSiliconFlow = baseUrl.toLowerCase().includes("siliconflow");

    const buildBody = async (withZeroShot: boolean): Promise<Record<string, unknown>> => {
      const payload: Record<string, unknown> = {
        model,
        input: text,
        voice,
        response_format: responseFormat,
        speed,
      };
      if (withZeroShot && isSiliconFlow && input.referAudioBlob && input.referAudioText?.trim()) {
        const dataUri = await blobToDataUri(input.referAudioBlob);
        payload.references = [
          {
            audio: dataUri,
            text: input.referAudioText.trim(),
          },
        ];
        delete payload.voice;
      }
      return payload;
    };

    const sendRequest = async (payload: Record<string, unknown>) =>
      http({
        url: `${baseUrl}/audio/speech`,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify(payload),
        timeoutMs: 45_000,
        signal: input.signal,
      });

    let resp = await sendRequest(await buildBody(enableZeroShot));
    if (!resp.ok && enableZeroShot && isSiliconFlow && input.referAudioBlob) {
      // Retry with preset voice when zero-shot cloning fails on endpoint validation
      resp = await sendRequest(await buildBody(false));
    }

    if (!resp.ok || resp.body.byteLength < 64) {
      return null;
    }

    const mime =
      resp.headers["content-type"]?.split(";")[0]?.trim() ||
      (responseFormat === "wav" ? "audio/wav" : responseFormat === "opus" ? "audio/ogg" : "audio/mpeg");
    return toSafeBlob(resp.body, mime);
  },
};
