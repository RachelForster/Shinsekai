import type { StandaloneHttpClient } from "../../httpClient";
import type { StandaloneTtsAdapter, StandaloneTtsInput } from "../types";

export const gptSovitsCloudAdapter: StandaloneTtsAdapter = {
  id: "gpt-sovits-api",
  label: "远程 GPT-SoVITS 服务 (云端/自建局域网)",
  browserCors: "proxy-only",
  description: "直连远程或局域网 GPT-SoVITS v2 HTTP API (/tts)，适合手机 App 直连自建语音服务器。",
  schema: {
    base_api_url: {
      label: "GPT-SoVITS 服务地址",
      type: "str",
      default: "http://127.0.0.1:9880",
    },
    api_key: {
      label: "鉴权 Token（可选）",
      type: "str",
      secret: true,
      default: "",
    },
    default_refer_wav_path: {
      label: "服务端参考音频路径",
      type: "str",
      default: "",
    },
    default_prompt_text: {
      label: "参考音频文本",
      type: "str",
      default: "",
    },
    default_prompt_language: {
      label: "参考音频语种",
      type: "str",
      choices: ["zh", "ja", "en"],
      default: "zh",
    },
    text_lang: {
      label: "合成文本语种",
      type: "str",
      choices: ["auto", "zh", "ja", "en"],
      default: "auto",
    },
  },
  async synthesize(
    input: StandaloneTtsInput,
    extra: Record<string, unknown>,
    http: StandaloneHttpClient,
  ): Promise<Blob | null> {
    const text = input.text.trim();
    const baseUrl = (typeof extra.base_api_url === "string" ? extra.base_api_url.trim() : "").replace(
      /\/+$/,
      "",
    );
    if (!text || !baseUrl) return null;

    const apiKey = typeof extra.api_key === "string" ? extra.api_key.trim() : "";
    const refAudioPath =
      typeof extra.default_refer_wav_path === "string" ? extra.default_refer_wav_path.trim() : "";
    const promptText =
      (input.referAudioText?.trim() ||
        (typeof extra.default_prompt_text === "string" ? extra.default_prompt_text.trim() : ""));
    const promptLang =
      input.referAudioLang?.trim() ||
      (typeof extra.default_prompt_language === "string" ? extra.default_prompt_language.trim() : "zh") ||
      "zh";
    const textLang =
      typeof extra.text_lang === "string" && extra.text_lang.trim() ? extra.text_lang.trim() : "auto";

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (apiKey) {
      headers.Authorization = `Bearer ${apiKey}`;
    }

    const resp = await http({
      url: `${baseUrl}/tts`,
      method: "POST",
      headers,
      body: JSON.stringify({
        text,
        text_lang: textLang,
        ref_audio_path: refAudioPath,
        prompt_text: promptText,
        prompt_lang: promptLang,
        speed_factor: input.speed ?? 1.0,
        media_type: "wav",
      }),
      timeoutMs: 60_000,
      signal: input.signal,
    });

    if (!resp.ok || resp.body.byteLength < 64) {
      return null;
    }
    const copy = new Uint8Array(resp.body.byteLength);
    copy.set(resp.body);
    const mime = resp.headers["content-type"]?.split(";")[0]?.trim() || "audio/wav";
    return new Blob([copy], { type: mime });
  },
};
