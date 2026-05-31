import { RefreshCw } from "lucide-react";

import type { AdapterExtraFieldSchema, ApiConfig } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import type { LlmModelOption } from "../../shared/platform/types";
import { AsyncButton, Select, Switch, TextInput } from "../../shared/ui";
import { AdapterExtraForm } from "./AdapterExtraForm";
import { EditableModelSelect, ModelCapabilityBadge } from "./EditableModelSelect";

interface LlmConnectionSectionProps {
  activeApiKey: string;
  activeModel: string;
  availableModelOptions: LlmModelOption[];
  disabled: boolean;
  draft: ApiConfig;
  fetchModelsPending: boolean;
  llmExtraSchema: Record<string, AdapterExtraFieldSchema>;
  llmProviderSelectOptions: Array<{ label: string; value: string }>;
  modelCandidateListId: string;
  modelUnsupportedThinking: boolean;
  onAdapterExtraChange: (key: string, value: unknown) => void;
  onDraftPatch: (patch: Partial<ApiConfig>) => void;
  onFetchModels: () => void;
  onProviderChange: (provider: string) => void;
  onProviderMapChange: (key: "llm_api_key" | "llm_model", value: string) => void;
  selectedOption?: LlmModelOption;
}

export function LlmConnectionSection({
  activeApiKey,
  activeModel,
  availableModelOptions,
  disabled,
  draft,
  fetchModelsPending,
  llmExtraSchema,
  llmProviderSelectOptions,
  modelCandidateListId,
  modelUnsupportedThinking,
  onAdapterExtraChange,
  onDraftPatch,
  onFetchModels,
  onProviderChange,
  onProviderMapChange,
  selectedOption,
}: LlmConnectionSectionProps) {
  const { t } = useI18n();

  return (
    <section className="section">
      <div className="section__header">
        <h2 className="section__title">{t("api.llm.connectionTitle")}</h2>
      </div>
      <label className="field-row">
        <span className="field-row__label">{t("api.llm.provider")}</span>
        <span className="field-row__control">
          <Select
            disabled={disabled}
            onChange={(event) => onProviderChange(event.target.value)}
            value={draft.llm_provider}
          >
            {llmProviderSelectOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </span>
      </label>
      <label className="field-row">
        <span className="field-row__label">{t("api.llm.baseUrl")}</span>
        <span className="field-row__control">
          <TextInput
            disabled={disabled}
            onChange={(event) => onDraftPatch({ llm_base_url: event.target.value })}
            placeholder="https://api.example.com/v1"
            type="url"
            value={draft.llm_base_url}
          />
        </span>
      </label>
      <label className="field-row">
        <span className="field-row__label">{t("api.llm.apiKey")}</span>
        <span className="field-row__control">
          <TextInput
            disabled={disabled}
            onChange={(event) => onProviderMapChange("llm_api_key", event.target.value)}
            type="password"
            value={activeApiKey}
          />
        </span>
      </label>
      <label className="field-row">
        <span className="field-row__label">{t("api.llm.model")}</span>
          <span className="field-row__control">
            <span className="api-page__model-control">
              <EditableModelSelect
                disabled={disabled}
                id={modelCandidateListId}
                onChange={(value) => onProviderMapChange("llm_model", value)}
                options={availableModelOptions}
                placeholder={t("api.llm.modelPlaceholder")}
                value={activeModel}
              />
              <AsyncButton
                icon={<RefreshCw aria-hidden className="button__icon" />}
                loading={fetchModelsPending}
                onClick={onFetchModels}
              >
                {fetchModelsPending ? t("api.llm.fetching") : t("api.llm.fetchModels")}
              </AsyncButton>
            </span>
            {selectedOption?.tags.length ? (
              <div className="llm-model-badges">
                {selectedOption.tags.map((tag) => (
                  <ModelCapabilityBadge key={tag} tag={tag} />
                ))}
              </div>
            ) : null}
          </span>
        </label>
      <label className="field-row">
        <span className="field-row__label">{t("api.llm.streaming")}</span>
        <span className="field-row__control">
          <Switch
            checked={draft.is_streaming}
            disabled={disabled}
            onChange={(e) => onDraftPatch({ is_streaming: e.target.checked })}
          />
        </span>
      </label>
      <AdapterExtraForm
        disabled={disabled}
        modelUnsupportedThinking={modelUnsupportedThinking}
        onChange={onAdapterExtraChange}
        schema={llmExtraSchema}
        values={draft.llm_extra_configs?.[draft.llm_provider] ?? {}}
      />
    </section>
  );
}
