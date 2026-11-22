import type { ApiConfig } from "./types";

export const DEFAULT_PERCEPTION_MODEL = "Qwen/Qwen3-VL-2B-Instruct";
export const GGUF_PERCEPTION_MODEL = "Qwen/Qwen3-VL-2B-Instruct-GGUF:Q4_K_M";

export function perceptionModelSettings(config: ApiConfig) {
  const model = config.perception_model?.trim() || DEFAULT_PERCEPTION_MODEL;
  const legacyGguf = model === GGUF_PERCEPTION_MODEL;
  return {
    perception_model: legacyGguf ? DEFAULT_PERCEPTION_MODEL : model,
    perception_use_gguf: legacyGguf || Boolean(config.perception_use_gguf),
  };
}

export function effectivePerceptionModel(config: ApiConfig): string {
  const settings = perceptionModelSettings(config);
  return settings.perception_use_gguf ? GGUF_PERCEPTION_MODEL : settings.perception_model;
}
