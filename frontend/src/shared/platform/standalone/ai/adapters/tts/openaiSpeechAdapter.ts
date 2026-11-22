import { LLM_PROVIDER_SILICONFLOW } from "../../../../../constants";
import { translateRuntimeMessage } from "../../../../../i18n/runtimeLanguage";
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
  const siliconKey = typeof keys[LLM_PROVIDER_SILICONFLOW] === "string" ? keys[LLM_PROVIDER_SILICONFLOW].trim() : "";
  const activeKey =
    typeof keys[input.apiConfig.llm_provider] === "string" ? keys[input.apiConfig.llm_provider].trim() : "";
  return siliconKey || activeKey;
}

export const openaiSpeechTtsAdapter: StandaloneTtsAdapter = {
  id: "openai-speech",
  get label() {
    return translateRuntimeMessage("plat.standalone.tts.openaiLabel");
  },
  browserCors: "supported",
  get description() {
    return translateRuntimeMessage("plat.standalone.tts.openaiDesc");
  },
  schema: {
    reuse_llm_key: {
      get label() {
        return translateRuntimeMessage("plat.standalone.tts.openaiReuseKey");
      },
      type: "bool",
      default: true,
    },
    api_key: {
      get label() {
        return translateRuntimeMessage("plat.standalone.tts.openaiApiKey");
      },
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
      get label() {
        return translateRuntimeMessage("plat.standalone.tts.openaiModelId");
      },
      type: "str",
      default: "FunAudioLLM/CosyVoice2-0.5B",
    },
    default_voice_id: {
      get label() {
        return translateRuntimeMessage("plat.standalone.tts.defaultVoice");
      },
      type: "str",
      default: "FunAudioLLM/CosyVoice2-0.5B:claire",
    },
    enable_zero_shot: {
      get label() {
        return translateRuntimeMessage("plat.standalone.tts.openaiZeroShot");
      },
      type: "bool",
      default: true,
    },
    response_format: {
      get label() {
        return translateRuntimeMessage("plat.standalone.tts.audioFormat");
      },
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
      typeof extra.model === "string" && extra.model.trim() ? extra.model.trim() : "FunAudioLLM/CosyVoice2-0.5B";
    const voice =
      typeof extra.default_voice_id === "string" && extra.default_voice_id.trim()
        ? extra.default_voice_id.trim()
        : "FunAudioLLM/CosyVoice2-0.5B:claire";
    const responseFormat =
      typeof extra.response_format === "string" && extra.response_format.trim() ? extra.response_format.trim() : "mp3";
    const speed =
      typeof input.speed === "number" && Number.isFinite(input.speed) ? Math.min(2, Math.max(0.5, input.speed)) : 1.0;

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
