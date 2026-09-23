import { useEffect, useState } from "react";
import { DownloadCloud, RefreshCw } from "lucide-react";

import type { AdapterExtraFieldSchema, ApiConfig } from "../../entities/config/types";
import { downloadModelAsset, getModelAssetStatus } from "../../entities/model-assets/repository";
import { useI18n } from "../../shared/i18n";
import type { LlmModelOption, ModelAssetStatus, TaskSnapshot } from "../../shared/platform/types";
import { AsyncButton, Select, Switch, TaskProgress, TextInput, useToast } from "../../shared/ui";
import { AdapterExtraForm } from "./AdapterExtraForm";
import { EditableModelSelect } from "./EditableModelSelect";

interface VisionSettingsSectionProps {
  activeApiKey: string;
  activeBaseUrl: string;
  activeModel: string;
  availableModelOptions: LlmModelOption[];
  disabled: boolean;
  draft: ApiConfig;
  extraSchema: Record<string, AdapterExtraFieldSchema>;
  fetchModelsPending: boolean;
  id?: string;
  onAdapterExtraChange: (key: string, value: unknown) => void;
  onFetchModels: () => void;
  onProviderChange: (provider: string) => void;
  onProviderMapChange: (key: "vision_api_key" | "vision_base_url" | "vision_model", value: string) => void;
  providerOptions: Array<{ label: string; value: string }>;
  reuseLlmApiKey: boolean;
  sharedLlmProvider?: string;
}

const MOONDREAM_MODEL_ASSET = { assetId: "vision.moondream" } as const;

export function VisionSettingsSection({
  activeApiKey,
  activeBaseUrl,
  activeModel,
  availableModelOptions,
  disabled,
  draft,
  extraSchema,
  fetchModelsPending,
  id,
  onAdapterExtraChange,
  onFetchModels,
  onProviderChange,
  onProviderMapChange,
  providerOptions,
  reuseLlmApiKey,
  sharedLlmProvider,
}: VisionSettingsSectionProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [moondreamStatus, setMoondreamStatus] = useState<ModelAssetStatus | null>(null);
  const [moondreamTask, setMoondreamTask] = useState<TaskSnapshot | null>(null);
  const [moondreamBusy, setMoondreamBusy] = useState(false);
  const [moondreamChecking, setMoondreamChecking] = useState(false);
  const remoteProvider = !["auto", "moondream"].includes(draft.vision_provider.toLowerCase());
  const moondreamProvider = draft.vision_provider.toLowerCase() === "moondream";

  useEffect(() => {
    if (!moondreamProvider) return;
    let active = true;
    setMoondreamChecking(true);
    void getModelAssetStatus(MOONDREAM_MODEL_ASSET)
      .then((status) => {
        if (active) setMoondreamStatus(status);
      })
      .catch(() => {
        if (active) setMoondreamStatus(null);
      })
      .finally(() => {
        if (active) setMoondreamChecking(false);
      });
    return () => {
      active = false;
    };
  }, [moondreamProvider]);

  const downloadMoondream = async () => {
    setMoondreamBusy(true);
    setMoondreamTask(null);
    try {
      await downloadModelAsset(MOONDREAM_MODEL_ASSET, { onTaskUpdate: setMoondreamTask });
      setMoondreamStatus(await getModelAssetStatus(MOONDREAM_MODEL_ASSET));
      setMoondreamTask(null);
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.vision.modelDownloadFailed"),
        title: t("api.vision.title"),
      });
    } finally {
      setMoondreamBusy(false);
    }
  };

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <div>
          <h2 className="section__title">{t("api.vision.title")}</h2>
          <p className="section__description">{t("api.vision.description")}</p>
        </div>
      </div>
      <label className="field-row">
        <span className="field-row__label">{t("api.vision.provider")}</span>
        <span className="field-row__control">
          <Select
            aria-label={t("api.vision.provider")}
            disabled={disabled}
            onChange={(event) => onProviderChange(event.target.value)}
            value={draft.vision_provider}
          >
            {providerOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </span>
      </label>
      {remoteProvider ? (
        <>
          <label className="field-row">
            <span className="field-row__label">{t("api.vision.baseUrl")}</span>
            <span className="field-row__control">
              <TextInput
                disabled={disabled}
                onChange={(event) => onProviderMapChange("vision_base_url", event.target.value)}
                placeholder="https://api.deepseek.com"
                type="url"
                value={activeBaseUrl}
              />
            </span>
          </label>
          {sharedLlmProvider ? (
            <label className="field-row">
              <span className="field-row__label">{t("api.vision.reuseLlmApiKey")}</span>
              <span className="field-row__control">
                <Switch
                  aria-label={t("api.vision.reuseLlmApiKey")}
                  checked={reuseLlmApiKey}
                  disabled={disabled}
                  id="vision-reuse-llm-api-key"
                  onChange={(event) => onAdapterExtraChange("reuse_llm_api_key", event.currentTarget.checked)}
                />
                <span className="field-row__help">
                  {t("api.vision.reuseLlmApiKeyHelp", { provider: sharedLlmProvider })}
                </span>
              </span>
            </label>
          ) : null}
          <label className="field-row">
            <span className="field-row__label">{t("api.vision.apiKey")}</span>
            <span className="field-row__control">
              <TextInput
                disabled={disabled || reuseLlmApiKey}
                onChange={(event) => onProviderMapChange("vision_api_key", event.target.value)}
                type="password"
                value={activeApiKey}
              />
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("api.vision.model")}</span>
            <span className="field-row__control">
              <span className="api-page__model-control">
                <EditableModelSelect
                  disabled={disabled}
                  id="vision-model-candidates"
                  onChange={(value) => onProviderMapChange("vision_model", value)}
                  options={availableModelOptions}
                  placeholder={t("api.vision.modelPlaceholder")}
                  value={activeModel}
                />
                <AsyncButton
                  icon={<RefreshCw aria-hidden className="button__icon" />}
                  loading={fetchModelsPending}
                  onClick={onFetchModels}
                >
                  {fetchModelsPending ? t("api.vision.fetching") : t("api.vision.fetchModels")}
                </AsyncButton>
              </span>
            </span>
          </label>
        </>
      ) : null}
      {moondreamProvider ? (
        <div className="field-row" aria-live="polite">
          <span className="field-row__label">{t("api.vision.modelStatus")}</span>
          <span className="field-row__control">
            <span>
              {moondreamChecking
                ? t("api.vision.checkingModel")
                : moondreamStatus?.cached
                  ? t("api.vision.modelCached")
                  : t("api.vision.modelMissing")}
            </span>
            {!moondreamChecking && !moondreamStatus?.cached ? (
              <AsyncButton
                disabled={disabled}
                icon={<DownloadCloud aria-hidden className="button__icon" />}
                loading={moondreamBusy}
                onClick={() => void downloadMoondream()}
              >
                {moondreamBusy ? t("api.vision.downloadingModel") : t("api.vision.downloadModel")}
              </AsyncButton>
            ) : null}
            {moondreamTask ? <TaskProgress logLimit={0} task={moondreamTask} /> : null}
          </span>
        </div>
      ) : null}
      <AdapterExtraForm
        disabled={disabled}
        onChange={onAdapterExtraChange}
        schema={extraSchema}
        values={draft.vision_extra_configs?.[draft.vision_provider] ?? {}}
      />
    </section>
  );
}
