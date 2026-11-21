import { standaloneHttpJson, type StandaloneHttpClient } from "../../httpClient";
import type { StandaloneTtsAdapter, StandaloneTtsInput } from "../types";

interface MinimaxTtsResponse {
  data?: {
    audio?: string;
    status?: number;
  };
  base_resp?: {
    status_code?: number;
    status_msg?: string;
  };
}

function hexToBytes(hex: string): Uint8Array {
  const clean = hex.trim();
  const len = Math.floor(clean.length / 2);
  const out = new Uint8Array(len);
  for (let i = 0; i < len; i += 1) {
    out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

export const minimaxTtsAdapter: StandaloneTtsAdapter = {
  id: "minimax-tts",
  label: "MiniMax 云端语音 (T2A v2)",
  browserCors: "supported",
  description: "对齐仓库 minimax-tts 插件字段，调用 MiniMax T2A v2 合成高质量拟人语音。",
  schema: {
    api_key: {
      label: "MiniMax API Key",
      type: "str",
      secret: true,
      default: "",
    },
    group_id: {
      label: "Group ID",
      type: "str",
      default: "",
    },
    base_api_url: {
      label: "API Base URL",
      type: "str",
      default: "https://api.minimax.chat/v1",
    },
    model: {
      label: "模型",
      type: "str",
      default: "speech-01-turbo",
    },
    default_voice_id: {
      label: "默认音色 Voice ID",
      type: "str",
      default: "female-shaonv",
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

    const groupId = typeof extra.group_id === "string" ? extra.group_id.trim() : "";
    const baseUrl = (
      typeof extra.base_api_url === "string" && extra.base_api_url.trim()
        ? extra.base_api_url.trim()
        : "https://api.minimax.chat/v1"
    ).replace(/\/+$/, "");
    const model = typeof extra.model === "string" && extra.model.trim() ? extra.model.trim() : "speech-01-turbo";
    const voiceId =
      typeof extra.default_voice_id === "string" && extra.default_voice_id.trim()
        ? extra.default_voice_id.trim()
        : "female-shaonv";

    const query = groupId ? `?GroupId=${encodeURIComponent(groupId)}` : "";
    const { data } = await standaloneHttpJson<MinimaxTtsResponse>({
      url: `${baseUrl}/t2a_v2${query}`,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        text,
        stream: false,
        voice_setting: {
          voice_id: voiceId,
          speed: input.speed ?? 1.0,
          vol: input.volume ?? 1.0,
          pitch: 0,
        },
        audio_setting: {
          sample_rate: 32000,
          bitrate: 128000,
          format: "mp3",
          channel: 1,
        },
      }),
      timeoutMs: 45_000,
      signal: input.signal,
    });

    const hex = data.data?.audio;
    if (!hex) return null;
    const bytes = hexToBytes(hex);
    if (bytes.byteLength < 64) return null;
    const copy = new Uint8Array(bytes.byteLength);
    copy.set(bytes);
    return new Blob([copy], { type: "audio/mpeg" });
  },
};
