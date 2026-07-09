import { useRef, useState } from "react";
import { DownloadCloud } from "lucide-react";

import { getMemoryStatus } from "../../entities/config/repository";
import type { ApiConfig } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import type { Mem0Status, TaskSnapshot } from "../../shared/platform/types";
import { AsyncButton, NumberInput, Switch, TaskProgress, useToast } from "../../shared/ui";
import { clampInt } from "./apiSettingsUtils";

interface MemorySettingsSectionProps {
  disabled?: boolean;
  draft: ApiConfig;
  id?: string;
  onChange: (draft: ApiConfig) => void;
}

function memoryStatusLabel(status: Mem0Status | null, t: ReturnType<typeof useI18n>["t"]) {
  if (!status) {
    return t("api.memory.statusUnknown");
  }
  if (status.status === "ready") {
    return status.modelCached ? t("api.memory.readyCached") : t("api.memory.ready");
  }
  if (status.status === "loading" || status.status === "not_started") {
    return status.modelCached ? t("api.memory.loadingCached") : t("api.memory.downloading");
  }
  if (status.status === "missing_dependency") {
    return t("api.memory.missingDependency");
  }
  return status.message || status.task?.errorUserMessage || t("api.memory.error");
}

export function MemorySettingsSection({ disabled = false, draft, id, onChange }: MemorySettingsSectionProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [status, setStatus] = useState<Mem0Status | null>(null);
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  const [checking, setChecking] = useState(false);
  const pollTokenRef = useRef(0);

  const patch = (changes: Partial<ApiConfig>) => onChange({ ...draft, ...changes });

  const checkMemoryStatus = async () => {
    const token = pollTokenRef.current + 1;
    pollTokenRef.current = token;
    setChecking(true);
    try {
      let next = await getMemoryStatus();
      while (pollTokenRef.current === token) {
        setStatus(next);
        setTask(next.task ?? null);
        if (next.status !== "loading" && next.status !== "not_started") {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, next.modelCached ? 2000 : 3000));
        next = await getMemoryStatus();
      }
      if (next.status === "ready") {
        showToast({ kind: "success", title: t("api.memory.ready") });
      } else if (next.status === "missing_dependency" || next.status === "error") {
        showToast({
          kind: "error",
          message: next.message || next.task?.errorUserMessage || t("api.memory.error"),
          title: t("api.memory.title"),
        });
      }
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.memory.error"),
        title: t("api.memory.title"),
      });
    } finally {
      if (pollTokenRef.current === token) {
        setChecking(false);
      }
    }
  };

  return (
    <section className="section memory-settings page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("api.memory.title")}</h2>
        <AsyncButton
          disabled={disabled}
          icon={<DownloadCloud aria-hidden className="button__icon" />}
          loading={checking}
          onClick={checkMemoryStatus}
        >
          {checking ? t("api.memory.checking") : t("api.memory.downloadModel")}
        </AsyncButton>
      </div>
      <p className="section__description">{t("api.memory.description")}</p>
      <label className="field-row">
        <span className="field-row__label">{t("api.memory.enabled")}</span>
        <span className="field-row__control">
          <Switch
            checked={draft.memory_auto_enabled}
            disabled={disabled}
            id="memory-auto-enabled"
            onChange={(event) => patch({ memory_auto_enabled: event.currentTarget.checked })}
          />
        </span>
      </label>
      <label className="field-row">
        <span className="field-row__label">{t("api.memory.extractInterval")}</span>
        <span className="field-row__control">
          <NumberInput
            disabled={disabled || !draft.memory_auto_enabled}
            max={50}
            min={1}
            onChange={(event) =>
              patch({ memory_extract_interval_turns: clampInt(event.currentTarget.value, 5, 1, 50) })
            }
            step={1}
            value={draft.memory_extract_interval_turns}
          />
          <span className="field-row__help">{t("api.memory.extractIntervalHelp")}</span>
        </span>
      </label>
      <label className="field-row">
        <span className="field-row__label">{t("api.memory.searchLimit")}</span>
        <span className="field-row__control">
          <NumberInput
            disabled={disabled || !draft.memory_auto_enabled}
            max={20}
            min={1}
            onChange={(event) => patch({ memory_search_limit: clampInt(event.currentTarget.value, 5, 1, 20) })}
            step={1}
            value={draft.memory_search_limit}
          />
          <span className="field-row__help">{t("api.memory.searchLimitHelp")}</span>
        </span>
      </label>
      <label className="field-row">
        <span className="field-row__label">{t("api.memory.recentBuffer")}</span>
        <span className="field-row__control">
          <NumberInput
            disabled={disabled || !draft.memory_auto_enabled}
            max={64}
            min={2}
            onChange={(event) =>
              patch({ memory_recent_buffer_messages: clampInt(event.currentTarget.value, 16, 2, 64) })
            }
            step={1}
            value={draft.memory_recent_buffer_messages}
          />
          <span className="field-row__help">{t("api.memory.recentBufferHelp")}</span>
        </span>
      </label>
      <div className="field-row" aria-live="polite">
        <span className="field-row__label">{t("api.memory.modelStatus")}</span>
        <span className="field-row__control">
          <span className="memory-settings__status-value">{memoryStatusLabel(status, t)}</span>
          {task ? <TaskProgress logLimit={0} task={task} /> : null}
        </span>
      </div>
    </section>
  );
}
