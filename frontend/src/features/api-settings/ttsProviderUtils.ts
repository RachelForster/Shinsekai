import type { ApiConfig } from "../../entities/config/types";
import { LEGACY_TTS_NONE_LABEL } from "../../shared/constants";
import { translateRuntimeMessage, type TranslateFn } from "../../shared/i18n";

export const LEGACY_DEFAULT_TTS_SERVER_URL = "http://127.0.0.1:9880";
export const HTTPS_DEFAULT_TTS_SERVER_URL = "https://127.0.0.1:9880";
export const DEFAULT_TTS_SERVER_URL = LEGACY_DEFAULT_TTS_SERVER_URL;
export const QWEN3_TTS_GGUF_DEFAULT_URL = "http://127.0.0.1:9882";

const LOCAL_SERVER_TTS_PROVIDERS = new Set(["gpt-sovits", "genie-tts", "index-tts"]);
const REMOTE_SERVER_TTS_PROVIDERS = new Set(["kaggle-gpt-sovits"]);
const OPTIONAL_PATH_TTS_PROVIDERS = new Set(["qwen3-tts-gguf"]);
const SERVER_CONFIG_TTS_PROVIDERS = new Set([
  ...LOCAL_SERVER_TTS_PROVIDERS,
  ...REMOTE_SERVER_TTS_PROVIDERS,
  ...OPTIONAL_PATH_TTS_PROVIDERS,
]);
const TTS_PROVIDER_DEFAULT_URLS: Record<string, string> = {
  "genie-tts": DEFAULT_TTS_SERVER_URL,
  "gpt-sovits": DEFAULT_TTS_SERVER_URL,
  "index-tts": LEGACY_DEFAULT_TTS_SERVER_URL,
  "qwen3-tts-gguf": QWEN3_TTS_GGUF_DEFAULT_URL,
};
const BUILTIN_TTS_SERVER_URLS = new Set([
  LEGACY_DEFAULT_TTS_SERVER_URL,
  HTTPS_DEFAULT_TTS_SERVER_URL,
  DEFAULT_TTS_SERVER_URL,
  QWEN3_TTS_GGUF_DEFAULT_URL,
]);
const TTS_PROVIDER_ALIASES: Record<string, string> = {
  "genie tts": "genie-tts",
  "gpt sovits": "gpt-sovits",
  "gpt-sovits": "gpt-sovits",
  kaggle: "kaggle-gpt-sovits",
  "kaggle gpt sovits": "kaggle-gpt-sovits",
  "kaggle gpt-sovits": "kaggle-gpt-sovits",
  "kaggle-gpt-sovits": "kaggle-gpt-sovits",
  "llama-tts": "qwen3-tts-gguf",
  "qwen3 tts": "qwen3-tts-gguf",
  "qwen3 tts gguf": "qwen3-tts-gguf",
  "qwen3-tts": "qwen3-tts-gguf",
  "qwen3-tts-gguf": "qwen3-tts-gguf",
};

const defaultTtsTranslator: TranslateFn = (key, values) => translateRuntimeMessage(key, values);

export function normalizeTtsProvider(provider: string) {
  const normalized = String(provider || "")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return "gpt-sovits";
  }
  if (["none", "off", "disable", "disabled", LEGACY_TTS_NONE_LABEL].includes(normalized)) {
    return "none";
  }
  return TTS_PROVIDER_ALIASES[normalized] ?? normalized;
}

export function ttsSharedServerFieldCopy(provider: string, t: TranslateFn = defaultTtsTranslator) {
  switch (normalizeTtsProvider(provider)) {
    case "genie-tts":
      return {
        pathDescription: t("ops.api.tts.genie.pathDesc"),
        pathDisabledReason: undefined,
        pathLabel: t("ops.api.tts.genie.pathLabel"),
        pathPlaceholder: t("ops.api.tts.genie.pathPlaceholder"),
        urlDescription: t("ops.api.tts.genie.urlDesc"),
        urlLabel: t("ops.api.tts.genie.urlLabel"),
        urlPlaceholder: t("ops.api.tts.genie.urlPlaceholder"),
      };
    case "index-tts":
      return {
        pathDescription: t("ops.api.tts.indexTts.pathDesc"),
        pathDisabledReason: undefined,
        pathLabel: t("ops.api.tts.indexTts.pathLabel"),
        pathPlaceholder: t("ops.api.tts.indexTts.pathPlaceholder"),
        urlDescription: t("ops.api.tts.indexTts.urlDesc"),
        urlLabel: t("ops.api.tts.indexTts.urlLabel"),
        urlPlaceholder: t("ops.api.tts.indexTts.urlPlaceholder"),
      };
    case "kaggle-gpt-sovits":
      return {
        pathDescription: t("ops.api.tts.kaggle.pathDesc"),
        pathDisabledReason: t("ops.api.tts.kaggle.pathDisabledReason"),
        pathLabel: t("ops.api.tts.kaggle.pathLabel"),
        pathPlaceholder: t("ops.api.tts.kaggle.pathPlaceholder"),
        urlDescription: t("ops.api.tts.kaggle.urlDesc"),
        urlLabel: t("ops.api.tts.kaggle.urlLabel"),
        urlPlaceholder: t("ops.api.tts.kaggle.urlPlaceholder"),
      };
    case "gpt-sovits":
      return {
        pathDescription: t("ops.api.tts.gptSovits.pathDesc"),
        pathDisabledReason: undefined,
        pathLabel: t("ops.api.tts.gptSovits.pathLabel"),
        pathPlaceholder: t("ops.api.tts.gptSovits.pathPlaceholder"),
        urlDescription: t("ops.api.tts.gptSovits.urlDesc"),
        urlLabel: t("ops.api.tts.gptSovits.urlLabel"),
        urlPlaceholder: t("ops.api.tts.gptSovits.urlPlaceholder"),
      };
    case "qwen3-tts-gguf":
      return {
        pathDescription: t("ops.api.tts.qwen3Gguf.pathDesc"),
        pathDisabledReason: undefined,
        pathLabel: t("ops.api.tts.qwen3Gguf.pathLabel"),
        pathPlaceholder: t("ops.api.tts.qwen3Gguf.pathPlaceholder"),
        urlDescription: t("ops.api.tts.qwen3Gguf.urlDesc"),
        urlLabel: t("ops.api.tts.qwen3Gguf.urlLabel"),
        urlPlaceholder: t("ops.api.tts.qwen3Gguf.urlPlaceholder"),
      };
    default:
      return {
        pathDescription: t("ops.api.tts.default.pathDesc"),
        pathDisabledReason: undefined,
        pathLabel: t("ops.api.tts.default.pathLabel"),
        pathPlaceholder: t("ops.api.tts.default.pathPlaceholder"),
        urlDescription: t("ops.api.tts.default.urlDesc"),
        urlLabel: t("ops.api.tts.default.urlLabel"),
        urlPlaceholder: t("ops.api.tts.default.urlPlaceholder"),
      };
  }
}

export function defaultTtsServerUrl(provider: string) {
  return TTS_PROVIDER_DEFAULT_URLS[normalizeTtsProvider(provider)] ?? "";
}

export function ttsServerUrlOrDefault(provider: string, currentUrl: string) {
  const cleanUrl = String(currentUrl || "").trim();
  const defaultUrl = defaultTtsServerUrl(provider);
  if (defaultUrl && (!cleanUrl || BUILTIN_TTS_SERVER_URLS.has(cleanUrl))) {
    return defaultUrl;
  }
  return cleanUrl;
}

export function requiresTtsServerConfig(provider: string) {
  return SERVER_CONFIG_TTS_PROVIDERS.has(normalizeTtsProvider(provider));
}

export function requiresTtsWorkPath(provider: string) {
  return LOCAL_SERVER_TTS_PROVIDERS.has(normalizeTtsProvider(provider));
}

export function applyTtsProviderDefaults(config: ApiConfig, installedTtsBundlePath = ""): ApiConfig {
  const ttsProvider = normalizeTtsProvider(config.tts_provider);
  const cleanPath = String(config.gpt_sovits_api_path || "").trim();
  const defaultPath = String(installedTtsBundlePath || "").trim();
  return {
    ...config,
    gpt_sovits_api_path:
      ttsProvider === "kaggle-gpt-sovits"
        ? ""
        : requiresTtsWorkPath(ttsProvider) && !cleanPath && defaultPath
          ? defaultPath
          : cleanPath,
    gpt_sovits_url: ttsServerUrlOrDefault(ttsProvider, config.gpt_sovits_url),
    tts_provider: ttsProvider,
  };
}

export function applyDownloadedTtsBundle(config: ApiConfig, result: { path: string; provider: string }): ApiConfig {
  return applyTtsProviderDefaults(
    {
      ...config,
      gpt_sovits_api_path: result.path,
      tts_provider: result.provider,
    },
    result.path,
  );
}
