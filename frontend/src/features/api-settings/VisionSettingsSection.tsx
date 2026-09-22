import { RefreshCw } from "lucide-react";

import type { AdapterExtraFieldSchema, ApiConfig } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import type { LlmModelOption } from "../../shared/platform/types";
import { AsyncButton, Select, TextInput } from "../../shared/ui";
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
}

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
}: VisionSettingsSectionProps) {
  const { t } = useI18n();
  const remoteProvider = !["auto", "moondream"].includes(draft.vision_provider.toLowerCase());

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
          <label className="field-row">
            <span className="field-row__label">{t("api.vision.apiKey")}</span>
            <span className="field-row__control">
              <TextInput
                disabled={disabled}
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
      <AdapterExtraForm
        disabled={disabled}
        onChange={onAdapterExtraChange}
        schema={extraSchema}
        values={draft.vision_extra_configs?.[draft.vision_provider] ?? {}}
      />
    </section>
  );
}
