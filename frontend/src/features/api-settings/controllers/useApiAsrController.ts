import { useCallback } from "react";

import { useI18n } from "../../../shared/i18n";
import {
  asrComputeOptions,
  asrProviderOptions,
  normalizeAsrProvider,
  resolveAsrWhisperPresetValue,
  updateAsrExtraConfig,
  VOSK_MODEL_PATH,
  withCurrentOption,
} from "../apiSettingsUtils";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function useApiAsrController(ctx: ApiSettingsPageContext) {
  const { t } = useI18n();
  const activeAsrProvider = normalizeAsrProvider(ctx.systemDraft.asr_provider);
  const asrProviderSelectOptions = withCurrentOption(
    ctx.adapterCatalog?.asr?.length
      ? ctx.adapterCatalog.asr.map((option) => ({
          label: option.label || option.value,
          value: normalizeAsrProvider(option.value),
        }))
      : [...asrProviderOptions],
    activeAsrProvider,
  );
  const showWhisperFields = activeAsrProvider === "faster_whisper" || activeAsrProvider === "realtime_stt";
  const whisperPresetValue = resolveAsrWhisperPresetValue(ctx.systemDraft.asr_whisper_model_size);
  const customWhisperModel = whisperPresetValue === "__custom__";
  const currentAsrCompute = String(ctx.systemDraft.asr_whisper_compute_type ?? "");
  const asrComputeSelectOptions = withCurrentOption(
    asrComputeOptions.map((option) => ({
      label: "label" in option ? option.label : t(option.labelKey),
      value: option.value,
    })),
    currentAsrCompute,
  );
  const activeAsrSchema =
    ctx.adapterCatalog?.asr?.find((option) => normalizeAsrProvider(option.value) === activeAsrProvider)?.schema ?? {};
  const voskModelPath = String(ctx.draft.asr_extra_configs?.vosk?.model_path ?? VOSK_MODEL_PATH);

  const updateAsrExtra = useCallback(
    (provider: string, key: string, value: unknown) => {
      ctx.setDraft((current) => (current ? updateAsrExtraConfig(current, provider, key, value) : current));
    },
    [ctx.setDraft],
  );

  return {
    activeAsrProvider,
    activeAsrSchema,
    asrComputeSelectOptions,
    asrProviderSelectOptions,
    currentAsrCompute,
    customWhisperModel,
    showWhisperFields,
    updateAsrExtra,
    voskModelPath,
    whisperPresetValue,
  };
}
