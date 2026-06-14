import { useEffect, useState } from "react";
import { CheckCircle2, Monitor, Settings2, Sparkles, Wand2, type LucideIcon } from "lucide-react";

import type { AdapterExtraFieldSchema, ApiConfig } from "../../entities/config/types";
import type { SchemaErrorMap } from "../../entities/config/schema";
import { useI18n } from "../../shared/i18n";
import { Button, FilePicker, Select, TextInput } from "../../shared/ui";
import { AdapterExtraForm } from "./AdapterExtraForm";
import { applyT2iSetupMode, hasAdapterSchema, inferT2iSetupMode, type T2iSetupMode } from "./apiSettingsUtils";

interface T2iSetupSectionProps {
  disabled: boolean;
  draft: ApiConfig;
  errors: SchemaErrorMap<ApiConfig>;
  extraSchema: Record<string, AdapterExtraFieldSchema>;
  extraValues: Record<string, unknown>;
  id?: string;
  onAdapterExtraChange: (key: string, value: unknown) => void;
  onChange: (draft: ApiConfig) => void;
  providerOptions: Array<{ label: string; value: string }>;
}

const modeIcons = {
  custom: Settings2,
  local: Monitor,
  skip: CheckCircle2,
} satisfies Record<T2iSetupMode, LucideIcon>;

function patchT2i(draft: ApiConfig, patch: Partial<ApiConfig>): ApiConfig {
  return { ...draft, ...patch };
}

export function T2iSetupSection({
  disabled,
  draft,
  errors,
  extraSchema,
  extraValues,
  id,
  onAdapterExtraChange,
  onChange,
  providerOptions,
}: T2iSetupSectionProps) {
  const { t } = useI18n();
  const inferredMode = inferT2iSetupMode(draft);
  const [mode, setSelectedMode] = useState<T2iSetupMode>(inferredMode);
  const active = mode !== "skip";
  const showAdvanced = active || hasAdapterSchema(extraSchema);

  useEffect(() => {
    if (inferredMode !== "skip" || mode === "skip") {
      setSelectedMode(inferredMode);
    }
  }, [inferredMode, mode]);

  const setMode = (nextMode: T2iSetupMode) => {
    setSelectedMode(nextMode);
    onChange(applyT2iSetupMode(draft, nextMode));
  };

  const modeChoices: Array<{ description: string; label: string; mode: T2iSetupMode }> = [
    { description: t("api.t2i.modeSkipHint"), label: t("api.t2i.modeSkip"), mode: "skip" },
    { description: t("api.t2i.modeLocalHint"), label: t("api.t2i.modeLocal"), mode: "local" },
    { description: t("api.t2i.modeCustomHint"), label: t("api.t2i.modeCustom"), mode: "custom" },
  ];

  return (
    <section className="section t2i-setup page-section-anchor" id={id}>
      <div className="section__header">
        <div>
          <h2 className="section__title">{t("api.t2i.title")}</h2>
          <p className="section__description">{t("api.t2i.description")}</p>
        </div>
      </div>
      <div className="t2i-setup__modes" role="radiogroup">
        {modeChoices.map((choice) => {
          const Icon = modeIcons[choice.mode];
          const selected = mode === choice.mode;
          return (
            <button
              aria-checked={selected}
              className="t2i-mode"
              data-selected={selected || undefined}
              disabled={disabled}
              key={choice.mode}
              onClick={() => setMode(choice.mode)}
              role="radio"
              type="button"
            >
              <Icon aria-hidden className="t2i-mode__icon" />
              <span className="t2i-mode__copy">
                <span className="t2i-mode__label">{choice.label}</span>
                <span className="t2i-mode__description">{choice.description}</span>
              </span>
            </button>
          );
        })}
      </div>
      {active ? (
        <>
          <div className="form-grid form-grid--two">
            <label className="field-row">
              <span className="field-row__label">{t("api.t2i.provider")}</span>
              <span className="field-row__control">
                <Select
                  disabled={disabled}
                  onChange={(event) => onChange(patchT2i(draft, { t2i_provider: event.target.value }))}
                  value={draft.t2i_provider}
                >
                  {providerOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("api.t2i.apiUrl")}</span>
              <span className="field-row__control">
                <TextInput
                  disabled={disabled}
                  onChange={(event) => onChange(patchT2i(draft, { t2i_api_url: event.target.value }))}
                  placeholder="http://127.0.0.1:8188"
                  type="url"
                  value={draft.t2i_api_url}
                />
                {errors.t2i_api_url ? <span className="field-error">{errors.t2i_api_url}</span> : null}
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("api.t2i.workflow")}</span>
              <span className="field-row__control">
                <FilePicker
                  acceptedExtensions={[".json"]}
                  disabled={disabled}
                  onChange={(event) => onChange(patchT2i(draft, { t2i_default_workflow_path: event.target.value }))}
                  onPathChange={(path) => onChange(patchT2i(draft, { t2i_default_workflow_path: path }))}
                  pickLabel={t("common.chooseFile")}
                  pickerTitle={t("api.t2i.workflowPick")}
                  value={draft.t2i_default_workflow_path}
                />
              </span>
            </label>
            {mode === "local" ? (
              <label className="field-row">
                <span className="field-row__label">{t("api.t2i.comfyDir")}</span>
                <span className="field-row__control">
                  <FilePicker
                    disabled={disabled}
                    onChange={(event) => onChange(patchT2i(draft, { t2i_work_path: event.target.value }))}
                    onPathChange={(path) => onChange(patchT2i(draft, { t2i_work_path: path }))}
                    pickLabel={t("common.chooseFolder")}
                    pickerMode="directory"
                    pickerTitle={t("api.t2i.comfyDir")}
                    value={draft.t2i_work_path}
                  />
                </span>
              </label>
            ) : null}
          </div>
          <div className="t2i-setup__actions">
            <Button
              disabled={disabled}
              icon={<Wand2 aria-hidden className="button__icon" />}
              onClick={() => onChange(applyT2iSetupMode(draft, mode))}
              variant="ghost"
            >
              {t("api.t2i.quickDefaults")}
            </Button>
          </div>
        </>
      ) : null}
      {showAdvanced ? (
        <details className="t2i-setup__advanced">
          <summary className="t2i-setup__advanced-summary">
            <Sparkles aria-hidden className="t2i-setup__advanced-icon" />
            {t("api.t2i.advanced")}
          </summary>
          {active ? (
            <div className="form-grid form-grid--two api-extra-grid">
              <label className="field-row">
                <span className="field-row__label">{t("api.t2i.promptNode")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={disabled}
                    onChange={(event) => onChange(patchT2i(draft, { t2i_prompt_node_id: event.target.value }))}
                    value={draft.t2i_prompt_node_id}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("api.t2i.outputNode")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={disabled}
                    onChange={(event) => onChange(patchT2i(draft, { t2i_output_node_id: event.target.value }))}
                    value={draft.t2i_output_node_id}
                  />
                </span>
              </label>
            </div>
          ) : null}
          {hasAdapterSchema(extraSchema) ? (
            <AdapterExtraForm
              disabled={disabled}
              onChange={onAdapterExtraChange}
              schema={extraSchema}
              values={extraValues}
            />
          ) : null}
        </details>
      ) : null}
    </section>
  );
}
