import { useEffect, useRef, useState } from "react";
import { Download, ExternalLink } from "lucide-react";

import type { AdapterExtraFieldSchema, ApiConfig, SystemConfig } from "../../entities/config/types";
import { openExternal } from "../../entities/files/repository";
import { downloadModelAsset, getModelAssetStatus } from "../../entities/model-assets/repository";
import { useI18n } from "../../shared/i18n";
import type { ModelAssetStatus, TaskSnapshot } from "../../shared/platform/types";
import { Button, FilePicker, ModelDownloadDialog, Select, TextInput } from "../../shared/ui";
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
  id?: string;
  onAsrExtraChange: (provider: string, key: string, value: unknown) => void;
  onPersistSystemDraft: () => Promise<void>;
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
  id,
  onAsrExtraChange,
  onPersistSystemDraft,
  onSystemPatch,
  showWhisperFields,
  systemDraft,
  voskModelPath = VOSK_MODEL_PATH,
  whisperPresetValue,
}: AsrSettingsSectionProps) {
  const { t } = useI18n();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [modelDialogState, setModelDialogState] = useState<
    "checking" | "confirm" | "downloading" | "error" | "success"
  >("confirm");
  const [modelAssetStatus, setModelAssetStatus] = useState<ModelAssetStatus | null>(null);
  const [modelDownloadTask, setModelDownloadTask] = useState<TaskSnapshot | null>(null);
  const [modelDownloadError, setModelDownloadError] = useState<string | null>(null);
  const [retryAction, setRetryAction] = useState<"check" | "download">("check");
  const modelOperationTokenRef = useRef(0);
  const configuredWhisperModel = String(systemDraft.asr_whisper_model_size || "").trim();
  const whisperModel = configuredWhisperModel || (customWhisperModel ? "" : "small");
  const supportsWhisperDownload = activeAsrProvider === "faster_whisper" || activeAsrProvider === "realtime_stt";
  const modelBusy = modelDialogState === "checking" || modelDialogState === "downloading";
  const modelAssetRef = customWhisperModel
    ? ({ assetId: "asr.faster-whisper", configured: true } as const)
    : ({ assetId: "asr.faster-whisper", variant: whisperModel } as const);

  useEffect(() => {
    modelOperationTokenRef.current += 1;
    setModelDialogOpen(false);
    setModelAssetStatus(null);
    setModelDownloadTask(null);
    setModelDownloadError(null);
    setModelDialogState("confirm");
  }, [activeAsrProvider, whisperModel]);

  useEffect(
    () => () => {
      modelOperationTokenRef.current += 1;
    },
    [],
  );

  const checkWhisperModel = async () => {
    const token = modelOperationTokenRef.current + 1;
    modelOperationTokenRef.current = token;
    setRetryAction("check");
    setModelDialogOpen(true);
    setModelDialogState("checking");
    setModelAssetStatus(null);
    setModelDownloadTask(null);
    setModelDownloadError(null);
    try {
      if (customWhisperModel) {
        await onPersistSystemDraft();
        if (modelOperationTokenRef.current !== token) {
          return;
        }
      }
      const status = await getModelAssetStatus(modelAssetRef);
      if (modelOperationTokenRef.current !== token) {
        return;
      }
      setModelAssetStatus(status);
      if (status.source === "local") {
        if (status.cached) {
          setModelDialogState("success");
        } else {
          setModelDownloadError(t("system.asr.modelLocalMissing"));
          setModelDialogState("error");
        }
        return;
      }
      setModelDialogState(status.cached ? "success" : "confirm");
    } catch (error) {
      if (modelOperationTokenRef.current === token) {
        setModelDownloadError(error instanceof Error ? error.message : t("system.asr.modelDownloadFailed"));
        setModelDialogState("error");
      }
    }
  };

  const startWhisperModelDownload = async () => {
    const token = modelOperationTokenRef.current + 1;
    modelOperationTokenRef.current = token;
    setRetryAction("download");
    setModelDialogState("downloading");
    setModelDownloadTask(null);
    setModelDownloadError(null);
    try {
      const result = await downloadModelAsset(modelAssetRef, {
        onTaskUpdate(task) {
          if (modelOperationTokenRef.current === token) {
            setModelDownloadTask(task);
          }
        },
      });
      if (modelOperationTokenRef.current !== token) {
        return;
      }
      setModelAssetStatus(result);
      setModelDialogState("success");
    } catch (error) {
      if (modelOperationTokenRef.current === token) {
        setModelDownloadError(error instanceof Error ? error.message : t("system.asr.modelDownloadFailed"));
        setModelDialogState("error");
      }
    }
  };

  const modelStatusMessage = (() => {
    if (modelDialogState === "checking") {
      return t("system.asr.modelChecking");
    }
    if (modelDialogState === "downloading") {
      return t("system.asr.modelDownloading");
    }
    if (modelDialogState === "confirm") {
      return t("system.asr.modelMissing");
    }
    if (modelDialogState === "success") {
      return modelAssetStatus?.source === "local" ? t("system.asr.modelLocalReady") : t("system.asr.modelCached");
    }
    return undefined;
  })();

  return (
    <details className="section schema-section page-section-anchor" id={id}>
      <summary className="schema-section__summary">{t("system.asr.title")}</summary>
      <p className="section__description">{t("system.asr.hint")}</p>
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
      {showWhisperFields && supportsWhisperDownload ? (
        <div className="asr-model-download">
          <Button
            disabled={disabled || !whisperModel}
            icon={<Download aria-hidden className="button__icon" />}
            loading={modelBusy && modelDialogOpen}
            onClick={() => (modelBusy ? setModelDialogOpen(true) : void checkWhisperModel())}
          >
            {modelBusy
              ? modelDialogOpen
                ? t(modelDialogState === "downloading" ? "system.asr.modelDownloading" : "system.asr.modelChecking")
                : t("system.asr.modelViewProgress")
              : t("system.asr.modelDownload")}
          </Button>
          <span className="field-row__help">{t("system.asr.modelDownloadHint")}</span>
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
      <ModelDownloadDialog
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("system.asr.modelDownloadConfirm")}
        description={
          modelDialogState === "confirm"
            ? t("system.asr.modelDownloadConfirmBody", { model: whisperModel })
            : modelAssetStatus?.source === "local"
              ? t("system.asr.modelLocalDescription")
              : t("system.asr.modelDownloadDescription")
        }
        details={[
          { label: t("system.asr.modelName"), value: modelAssetStatus?.variant || whisperModel },
          ...(modelAssetStatus?.repoId
            ? [{ label: t("system.asr.modelRepository"), value: modelAssetStatus.repoId }]
            : []),
        ]}
        error={modelDownloadError}
        onClose={() => setModelDialogOpen(false)}
        onConfirm={() => void startWhisperModelDownload()}
        onRetry={() => void (retryAction === "download" ? startWhisperModelDownload() : checkWhisperModel())}
        open={modelDialogOpen}
        retryLabel={t("common.retry")}
        state={modelDialogState}
        statusMessage={modelStatusMessage}
        task={modelDownloadTask}
        title={t("system.asr.modelDownloadTitle")}
      />
    </details>
  );
}
