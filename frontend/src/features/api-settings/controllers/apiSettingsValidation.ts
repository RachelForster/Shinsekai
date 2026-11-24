import {
  buildPayloadFromSchema,
  hasSchemaErrors,
  type SchemaErrorMap,
  validatePayloadFromSchema,
} from "../../../entities/config/schema";
import type { ApiConfig, SystemConfig } from "../../../entities/config/types";
import type { FormGroupSchema } from "../../../shared/form-schema";
import type { useI18n } from "../../../shared/i18n";
import {
  activeMapValue,
  containsPathQuotes,
  effectiveVisionApiKey,
  effectiveVisionBaseUrl,
  effectiveVisionModel,
  normalizeApiAsrForSave,
  normalizeSystemAsrForSave,
  normalizeTtsProvider,
  requiresTtsServerConfig,
  requiresTtsWorkPath,
  thinkingUnsupported,
  visionProviderLlmProviders,
  visionProviderRequiresApiKey,
} from "../apiSettingsUtils";

export type ApiSettingsTranslate = ReturnType<typeof useI18n>["t"];

export function formatTtsBundleFailure(error: unknown, t: ApiSettingsTranslate) {
  const raw = error instanceof Error ? error.message : "";
  if (!raw.trim()) {
    return t("api.tts.bundleErrorUnknown");
  }
  const archiveMatch = raw.match(/archive saved at (.+)$/);
  const archive = archiveMatch?.[1]?.trim() ?? "";
  const clean = raw.replace(/; archive saved at .+$/, "").trim();
  let message: string;
  if (clean.startsWith("download:")) {
    message = t("api.tts.bundleErrorDownload", { detail: clean.slice("download:".length).trim() || clean });
  } else if (clean.startsWith("extract:")) {
    message = t("api.tts.bundleErrorExtract", { detail: clean.slice("extract:".length).trim() || clean });
  } else {
    message = clean;
  }
  return archive ? `${message}\n${t("api.tts.bundleErrorManual", { path: archive })}` : message;
}

export interface ApiSettingsValidationResult {
  errors: SchemaErrorMap<ApiConfig>;
  errorMessage?: string;
  payload?: { api: ApiConfig; system: SystemConfig };
}

export function validateAndBuildApiSettingsPayload({
  apiSchema,
  draft,
  systemDraft,
  t,
}: {
  apiSchema: Array<FormGroupSchema<ApiConfig>>;
  draft: ApiConfig;
  systemDraft: SystemConfig;
  t: ApiSettingsTranslate;
}): ApiSettingsValidationResult {
  const nextErrors = validatePayloadFromSchema(apiSchema, draft, t);
  if (hasSchemaErrors(nextErrors)) {
    return { errors: nextErrors, errorMessage: t("common.fixInvalidFields") };
  }

  const activeApiKey = activeMapValue(draft.llm_api_key, draft.llm_provider);
  const activeModel = activeMapValue(draft.llm_model, draft.llm_provider);
  if (!draft.llm_provider.trim() || !draft.llm_base_url.trim() || !activeApiKey.trim() || !activeModel.trim()) {
    return { errors: nextErrors, errorMessage: t("api.llm.required") };
  }
  if (containsPathQuotes(draft.llm_base_url)) {
    return { errors: nextErrors, errorMessage: t("ops.api.llm.baseUrlNoQuotes") };
  }

  const activeVisionBaseUrl = effectiveVisionBaseUrl(draft);
  const activeVisionApiKey = effectiveVisionApiKey(draft);
  const activeVisionModel = effectiveVisionModel(draft);
  if (
    !["auto", "moondream"].includes(draft.vision_provider.toLowerCase()) &&
    visionProviderLlmProviders[draft.vision_provider] &&
    (!activeVisionBaseUrl.trim() ||
      (visionProviderRequiresApiKey(draft.vision_provider) && !activeVisionApiKey.trim()) ||
      !activeVisionModel.trim())
  ) {
    return { errors: nextErrors, errorMessage: t("api.vision.required") };
  }
  if (containsPathQuotes(activeVisionBaseUrl)) {
    return { errors: nextErrors, errorMessage: t("api.vision.invalidBaseUrl") };
  }
  if (
    (draft.perception_enabled && !draft.perception_base_url.trim()) ||
    containsPathQuotes(draft.perception_base_url)
  ) {
    return { errors: nextErrors, errorMessage: t("api.perception.invalidBaseUrl") };
  }

  const ttsProvider = normalizeTtsProvider(draft.tts_provider);
  const isKaggleTts = ttsProvider === "kaggle-gpt-sovits";
  if (requiresTtsServerConfig(draft.tts_provider)) {
    if (!draft.gpt_sovits_url.trim()) {
      return { errors: nextErrors, errorMessage: t("ops.api.tts.urlRequired") };
    }
    if (requiresTtsWorkPath(ttsProvider) && !draft.gpt_sovits_api_path.trim()) {
      const message = t("ops.api.tts.pathRequired");
      return { errors: { ...nextErrors, gpt_sovits_api_path: message }, errorMessage: message };
    }
    if (containsPathQuotes(draft.gpt_sovits_url) || (!isKaggleTts && containsPathQuotes(draft.gpt_sovits_api_path))) {
      return { errors: nextErrors, errorMessage: t("ops.api.tts.noQuotes") };
    }
  }

  let nextConfig: ApiConfig = {
    ...draft,
    ...buildPayloadFromSchema(apiSchema, draft),
  };
  if (normalizeTtsProvider(nextConfig.tts_provider) === "kaggle-gpt-sovits") {
    nextConfig = {
      ...nextConfig,
      gpt_sovits_api_path: "",
    };
  }
  const nextSystem = normalizeSystemAsrForSave(systemDraft);
  nextConfig = normalizeApiAsrForSave(nextConfig, nextSystem);
  if (thinkingUnsupported(activeModel)) {
    nextConfig.llm_extra_configs = {
      ...nextConfig.llm_extra_configs,
      [nextConfig.llm_provider]: {
        ...(nextConfig.llm_extra_configs?.[nextConfig.llm_provider] ?? {}),
        thinking_enabled: false,
      },
    };
  }
  return { errors: nextErrors, payload: { api: nextConfig, system: nextSystem } };
}
