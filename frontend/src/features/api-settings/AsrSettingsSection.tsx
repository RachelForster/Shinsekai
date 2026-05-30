import { ExternalLink } from "lucide-react";

import type { AdapterExtraFieldSchema, ApiConfig, SystemConfig } from "../../entities/config/types";
import { openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { Button, FilePicker, Select, TextInput } from "../../shared/ui";
import { AdapterExtraForm } from "./AdapterExtraForm";
import {
  asrWhisperModelPresets,
  hasAdapterSchema,
  normalizeAsrProvider,
  VOSK_MODELS_URL,
  VOSK_MODEL_PATH,
} from "./apiSettingsUtils";

interface AsrSettingsSectionProps {
  activeAsrProvider: string;
  activeAsrSchema: Record<string, AdapterExtraFieldSchema>;
  asrComputeSelectOptions: Array<{ label: string; value: string }>;
  asrProviderSelectOptions: Array<{ label: string; value: string }>;
  currentAsrCompute: string;
  customWhisperModel: boolean;
  disabled: boolean;
  draft: ApiConfig;
  onAsrExtraChange: (provider: string, key: string, value: unknown) => void;
  onSystemPatch: (patch: Partial<SystemConfig>) => void;
  showWhisperFields: boolean;
  systemDraft: SystemConfig;
  voskModelPath?: string;
  whisperPresetValue: string;
}

export function AsrSettingsSection({
  activeAsrProvider,
  activeAsrSchema,
  asrComputeSelectOptions,
  asrProviderSelectOptions,
  currentAsrCompute,
  customWhisperModel,
  disabled,
  draft,
  onAsrExtraChange,
  onSystemPatch,
  showWhisperFields,
  systemDraft,
  voskModelPath = VOSK_MODEL_PATH,
  whisperPresetValue,
}: AsrSettingsSectionProps) {
  const { t } = useI18n();

  return (
    <section className="section">
      <div className="section__header">
        <div>
          <h2 className="section__title">{t("system.asr.title")}</h2>
          <p className="section__description">{t("system.asr.hint")}</p>
        </div>
      </div>
      {activeAsrProvider === "vosk" ? (
        <div className="asr-vosk-hint">
          <span>{t("system.asr.voskHint")}</span>
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal(VOSK_MODELS_URL)}
            variant="ghost"
          >
            {t("system.asr.voskModels")}
          </Button>
        </div>
      ) : null}
      <div className="form-grid form-grid--two">
        <label className="field-row">
          <span className="field-row__label">{t("system.asr.provider")}</span>
          <span className="field-row__control">
            <Select
              disabled={disabled}
              onChange={(event) => onSystemPatch({ asr_provider: normalizeAsrProvider(event.target.value) })}
              value={activeAsrProvider}
            >
              {asrProviderSelectOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("system.asr.language")}</span>
          <span className="field-row__control">
            <Select
              disabled={disabled}
              onChange={(event) => onSystemPatch({ asr_language: event.target.value })}
              value={systemDraft.asr_language ?? ""}
            >
              <option value="">{t("system.asr.followUi")}</option>
              <option value="en">{t("system.asr.langEn")}</option>
              <option value="zh">{t("system.asr.langZh")}</option>
              <option value="ja">{t("system.asr.langJa")}</option>
              <option value="yue">{t("system.asr.langYue")}</option>
            </Select>
          </span>
        </label>
        {activeAsrProvider === "vosk" ? (
          <label className="field-row">
            <span className="field-row__label">{t("system.asr.voskModelPath")}</span>
            <span className="field-row__control">
              <FilePicker
                disabled={disabled}
                onChange={(event) => onAsrExtraChange("vosk", "model_path", event.target.value)}
                onPathChange={(path) => onAsrExtraChange("vosk", "model_path", path)}
                pickLabel={t("common.chooseFolder")}
                pickerMode="directory"
                pickerTitle={t("system.asr.voskModelPath")}
                value={voskModelPath}
              />
            </span>
          </label>
        ) : null}
      </div>
      {showWhisperFields ? (
        <div className="form-grid form-grid--two api-extra-grid">
          <label className="field-row">
            <span className="field-row__label">{t("system.asr.whisperModel")}</span>
            <span className="field-row__control">
              <Select
                disabled={disabled}
                onChange={(event) => {
                  const next = event.target.value;
                  onSystemPatch({
                    asr_whisper_model_size:
                      next === "__custom__"
                        ? (asrWhisperModelPresets as readonly string[]).includes(systemDraft.asr_whisper_model_size)
                          ? ""
                          : systemDraft.asr_whisper_model_size
                        : next,
                  });
                }}
                value={whisperPresetValue}
              >
                {asrWhisperModelPresets.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
                <option value="__custom__">{t("system.asr.modelCustom")}</option>
              </Select>
              {customWhisperModel ? (
                <TextInput
                  className="asr-custom-model-input"
                  disabled={disabled}
                  onChange={(event) => onSystemPatch({ asr_whisper_model_size: event.target.value })}
                  placeholder={t("system.asr.modelCustomPlaceholder")}
                  value={
                    (asrWhisperModelPresets as readonly string[]).includes(systemDraft.asr_whisper_model_size)
                      ? ""
                      : systemDraft.asr_whisper_model_size
                  }
                />
              ) : null}
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("system.asr.device")}</span>
            <span className="field-row__control">
              <Select
                disabled={disabled}
                onChange={(event) => onSystemPatch({ asr_whisper_device: event.target.value })}
                value={systemDraft.asr_whisper_device || "auto"}
              >
                <option value="auto">{t("system.asr.deviceAuto")}</option>
                <option value="cuda">CUDA</option>
                <option value="cpu">CPU</option>
              </Select>
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("system.asr.computeType")}</span>
            <span className="field-row__control">
              <Select
                disabled={disabled}
                onChange={(event) => onSystemPatch({ asr_whisper_compute_type: event.target.value })}
                value={currentAsrCompute}
              >
                {asrComputeSelectOptions.map((option) => (
                  <option key={option.value || "__auto__"} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </span>
          </label>
        </div>
      ) : null}
      {activeAsrProvider !== "vosk" && hasAdapterSchema(activeAsrSchema) ? (
        <AdapterExtraForm
          disabled={disabled}
          onChange={(key, value) => onAsrExtraChange(activeAsrProvider, key, value)}
          schema={activeAsrSchema}
          values={draft.asr_extra_configs?.[activeAsrProvider] ?? {}}
        />
      ) : null}
    </section>
  );
}
