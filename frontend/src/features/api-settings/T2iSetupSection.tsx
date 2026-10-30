import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Monitor, Settings2, Sparkles, Wand2, Wifi, type LucideIcon } from "lucide-react";

import { testComfyuiConnection } from "../../entities/config/repository";
import type { AdapterExtraFieldSchema, ApiConfig } from "../../entities/config/types";
import type { SchemaErrorMap } from "../../entities/config/schema";
import { useI18n } from "../../shared/i18n";
import type { ComfyUIConnectionTestResult } from "../../shared/platform/types";
import { AsyncButton, Button, ComfyUIConnectionGuide, FilePicker, Select, Switch, TextInput } from "../../shared/ui";
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
  const isComfy = draft.t2i_provider.trim().toLowerCase() === "comfyui";
  const [checking, setChecking] = useState(false);
  const [connection, setConnection] = useState<ComfyUIConnectionTestResult | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const connectionRequest = useRef(0);
  const autoStart =
    typeof extraValues.auto_start === "boolean" ? extraValues.auto_start : Boolean(draft.t2i_work_path.trim());
  const advancedSchema = Object.fromEntries(
    Object.entries(extraSchema).filter(
      ([key]) => !isComfy || (key !== "auto_start" && (autoStart || key !== "startup_args")),
    ),
  );
  const showAdvanced = active || hasAdapterSchema(advancedSchema);

  useEffect(() => {
    connectionRequest.current += 1;
    setChecking(false);
    setConnection(null);
    setConnectionError(false);
    return () => {
      connectionRequest.current += 1;
    };
  }, [active, isComfy, draft.t2i_api_url]);

  const checkConnection = async () => {
    const requestId = ++connectionRequest.current;
    setChecking(true);
    setConnection(null);
    setConnectionError(false);
    try {
      const result = await testComfyuiConnection({ baseUrl: draft.t2i_api_url.trim() });
      if (requestId === connectionRequest.current) setConnection(result);
    } catch {
      if (requestId === connectionRequest.current) setConnectionError(true);
    } finally {
      if (requestId === connectionRequest.current) setChecking(false);
    }
  };

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
          {isComfy ? (
            <div className="t2i-setup__connection">
              <Switch
                checked={autoStart}
                disabled={disabled}
                onChange={(event) => onAdapterExtraChange("auto_start", event.target.checked)}
              >
                {t("api.t2i.autoStart")}
              </Switch>
              <p className="t2i-setup__hint">{t(autoStart ? "api.t2i.autoStartHint" : "api.t2i.manualStartHint")}</p>
              <details className="t2i-setup__guide">
                <summary>{t("comfyGuide.title")}</summary>
                <ComfyUIConnectionGuide />
              </details>
            </div>
          ) : null}
          <div className="form-grid form-grid--two">
            <label className="field-row">
              <span className="field-row__label">{t("api.t2i.provider")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("api.t2i.provider")}
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
                <div className="t2i-setup__url-control">
                  <TextInput
                    aria-label={t("api.t2i.apiUrl")}
                    disabled={disabled}
                    onChange={(event) => onChange(patchT2i(draft, { t2i_api_url: event.target.value }))}
                    placeholder="http://127.0.0.1:8188"
                    type="url"
                    value={draft.t2i_api_url}
                  />
                  {isComfy ? (
                    <AsyncButton
                      disabled={disabled || !draft.t2i_api_url.trim()}
                      icon={<Wifi aria-hidden className="button__icon" />}
                      loading={checking}
                      onClick={() => void checkConnection()}
                      tooltip={t("api.t2i.connectionHint")}
                    >
                      {t(checking ? "api.t2i.testingConnection" : "api.t2i.testConnection")}
                    </AsyncButton>
                  ) : null}
                </div>
                {errors.t2i_api_url ? <span className="field-error">{errors.t2i_api_url}</span> : null}
                {isComfy ? <span className="t2i-setup__hint">{t("api.t2i.apiUrlHint")}</span> : null}
                {connection && isComfy ? (
                  <div className="t2i-setup__connection-result" data-ok={connection.ok} role="status">
                    <p>
                      {t(`api.t2i.connection.${connection.code}`)}
                      {connection.httpStatus ? ` (HTTP ${connection.httpStatus})` : ""}
                      {connection.ok && connection.serverVersion ? ` (ComfyUI ${connection.serverVersion})` : ""}
                    </p>
                    {connection.ok ? <p className="t2i-setup__hint">{t("api.t2i.connectionScope")}</p> : null}
                  </div>
                ) : null}
                {connectionError && isComfy ? (
                  <p className="field-error" role="alert">
                    {t("api.t2i.connectionRequestFailed")}
                  </p>
                ) : null}
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("api.t2i.workflow")}</span>
              <span className="field-row__control">
                <FilePicker
                  aria-label={t("api.t2i.workflow")}
                  acceptedExtensions={[".json"]}
                  disabled={disabled}
                  onChange={(event) => onChange(patchT2i(draft, { t2i_default_workflow_path: event.target.value }))}
                  onPathChange={(path) => onChange(patchT2i(draft, { t2i_default_workflow_path: path }))}
                  pickLabel={t("common.chooseFile")}
                  pickerTitle={t("api.t2i.workflowPick")}
                  value={draft.t2i_default_workflow_path}
                />
                {isComfy ? <span className="t2i-setup__hint">{t("api.t2i.workflowHint")}</span> : null}
              </span>
            </label>
            {isComfy && autoStart ? (
              <label className="field-row">
                <span className="field-row__label">{t("api.t2i.comfyDir")}</span>
                <span className="field-row__control">
                  <FilePicker
                    aria-label={t("api.t2i.comfyDir")}
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
          {hasAdapterSchema(advancedSchema) ? (
            <AdapterExtraForm
              disabled={disabled}
              onChange={onAdapterExtraChange}
              schema={advancedSchema}
              values={extraValues}
            />
          ) : null}
        </details>
      ) : null}
    </section>
  );
}
