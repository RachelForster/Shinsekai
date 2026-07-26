import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { DownloadCloud } from "lucide-react";

import { installMissingRuntimeDependency } from "../../entities/chat/repository";
import { getMemoryStatus } from "../../entities/config/repository";
import type { ApiConfig } from "../../entities/config/types";
import { downloadModelAsset } from "../../entities/model-assets/repository";
import { isTauriDesktop, restartDesktopBridge } from "../../shared/desktop/desktopApi";
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

const MEMORY_EMBEDDING_ASSET = { assetId: "memory.embedding" } as const;

function dependencyPackageLabel(packageName: string | undefined, fallback: string) {
  const label = String(packageName || "")
    .replace(/(?:\[|[<>=!~]).*$/, "")
    .trim();
  return label || fallback;
}

function memoryStatusLabel(status: Mem0Status | null, t: ReturnType<typeof useI18n>["t"]) {
  if (!status) {
    return t("api.memory.statusUnknown");
  }
  if (status.status === "missing_dependency") {
    return t("api.memory.missingDependency", { packageName: status.packageName || "mem0ai" });
  }
  if (status.status === "error") {
    return t("api.memory.error");
  }
  if (status.status === "ready") {
    return t("api.memory.setupReady");
  }
  if (status.status === "loading") {
    return status.modelCached ? t("api.memory.loadingCached") : t("api.memory.downloading");
  }
  return status.modelCached ? t("api.memory.setupReady") : t("api.memory.setupModelMissing");
}

function memoryActionLabel(status: Mem0Status | null, t: ReturnType<typeof useI18n>["t"]) {
  if (!status) {
    return t("api.memory.checkModel");
  }
  if (status.status === "missing_dependency") {
    return t("api.memory.installDependency");
  }
  if (status.status === "error" || status.status === "loading" || status.modelCached) {
    return t("api.memory.recheckModel");
  }
  return t("api.memory.downloadModel");
}

function memoryTaskLabels(task: TaskSnapshot, t: ReturnType<typeof useI18n>["t"], dependencyPackage = "mem0ai") {
  const dependencyTask = task.kind === "runtime-dependency-install";
  const phase =
    task.phase === "pip"
      ? t("api.memory.installingDependency", { packageName: dependencyPackage })
      : task.phase === "queued"
        ? t("api.memory.taskInProgress")
        : task.phase === "download"
          ? t("api.memory.downloading")
          : task.phase === "verify"
            ? t("api.memory.taskVerifying")
            : task.phase === "completed"
              ? t(dependencyTask ? "api.memory.dependencyInstalled" : "api.memory.modelCached")
              : task.phase === "failed"
                ? t(dependencyTask ? "api.memory.dependencyInstallFailed" : "api.memory.modelDownloadFailed")
                : undefined;
  const status =
    task.status === "running"
      ? t("api.memory.taskInProgress")
      : task.status === "succeeded"
        ? t(dependencyTask ? "api.memory.dependencyInstalled" : "api.memory.modelCached")
        : task.status === "failed"
          ? t(dependencyTask ? "api.memory.dependencyInstallFailed" : "api.memory.modelDownloadFailed")
          : undefined;
  return { phase, status };
}

function memoryBusyLabel(task: TaskSnapshot | null, t: ReturnType<typeof useI18n>["t"], dependencyPackage?: string) {
  if (!task) {
    return dependencyPackage
      ? t("api.memory.installingDependency", { packageName: dependencyPackage })
      : t("api.memory.checking");
  }
  return memoryTaskLabels(task, t, dependencyPackage).phase || t("api.memory.checking");
}

export function MemorySettingsSection({ disabled = false, draft, id, onChange }: MemorySettingsSectionProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [status, setStatus] = useState<Mem0Status | null>(null);
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkingEnable, setCheckingEnable] = useState(false);
  const [installingDependencyPackage, setInstallingDependencyPackage] = useState<string>();
  const operationInFlightRef = useRef(false);
  const operationTokenRef = useRef(0);
  const draftRef = useRef(draft);
  draftRef.current = draft;

  useEffect(() => {
    const token = operationTokenRef.current + 1;
    operationTokenRef.current = token;
    void getMemoryStatus({ startLoading: false })
      .then((next) => {
        if (operationTokenRef.current === token) {
          setStatus(next);
          setTask(next.task ?? null);
        }
      })
      .catch(() => {
        // Keep the neutral "not checked" state when the passive cache read fails.
      });
    return () => {
      operationTokenRef.current += 1;
    };
  }, []);

  const patch = (changes: Partial<ApiConfig>) => onChange({ ...draftRef.current, ...changes });

  const handleMemoryAutoChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const enabled = event.currentTarget.checked;
    if (!enabled) {
      patch({ memory_auto_enabled: false });
      return;
    }
    if (operationInFlightRef.current) {
      return;
    }

    operationInFlightRef.current = true;
    const token = operationTokenRef.current + 1;
    operationTokenRef.current = token;
    setCheckingEnable(true);
    try {
      const next = await getMemoryStatus({ startLoading: false });
      if (operationTokenRef.current !== token) {
        return;
      }
      setStatus(next);
      setTask(next.task ?? null);

      if (next.status === "error") {
        showToast({ kind: "error", message: t("api.memory.error"), title: t("api.memory.title") });
        return;
      }
      if (next.status === "missing_dependency" || !next.modelCached) {
        showToast({
          kind: "info",
          message: t("api.memory.enableRequiresSetup"),
          title: t("api.memory.title"),
        });
        return;
      }
      patch({ memory_auto_enabled: true });
    } catch {
      if (operationTokenRef.current === token) {
        showToast({ kind: "error", message: t("api.memory.error"), title: t("api.memory.title") });
      }
    } finally {
      operationInFlightRef.current = false;
      if (operationTokenRef.current === token) {
        setCheckingEnable(false);
      }
    }
  };

  const prepareMemory = async () => {
    if (operationInFlightRef.current) {
      return;
    }
    operationInFlightRef.current = true;
    const token = operationTokenRef.current + 1;
    operationTokenRef.current = token;
    setChecking(true);
    setTask(null);
    try {
      let next = await getMemoryStatus({ startLoading: false });
      if (operationTokenRef.current !== token) {
        return;
      }
      setStatus(next);
      setTask(next.task ?? null);

      if (next.status === "missing_dependency") {
        const missing = next;
        setInstallingDependencyPackage(dependencyPackageLabel(missing.packageName, "mem0ai"));
        await installMissingRuntimeDependency(
          { moduleName: missing.moduleName?.trim() || "mem0" },
          {
            onTaskUpdate(nextTask) {
              if (operationTokenRef.current === token) {
                setTask(nextTask);
              }
            },
          },
        );
        if (isTauriDesktop()) {
          await restartDesktopBridge();
        }
        if (operationTokenRef.current !== token) {
          return;
        }
        setTask(null);
        setInstallingDependencyPackage(undefined);
        next = await getMemoryStatus({ startLoading: false });
        if (operationTokenRef.current !== token) {
          return;
        }
        setStatus(next);
        setTask(next.task ?? null);
      }

      if (next.status === "missing_dependency" || next.status === "error" || next.status === "loading") {
        if (next.status !== "loading") {
          showToast({
            kind: "error",
            message:
              next.status === "missing_dependency"
                ? t("api.memory.missingDependency", { packageName: next.packageName || "mem0ai" })
                : t("api.memory.error"),
            title: t("api.memory.title"),
          });
        }
        return;
      }
      if (next.modelCached) {
        return;
      }

      const result = await downloadModelAsset(MEMORY_EMBEDDING_ASSET, {
        onTaskUpdate(nextTask) {
          if (operationTokenRef.current === token) {
            setTask(nextTask);
          }
        },
      });
      if (operationTokenRef.current !== token) {
        return;
      }
      setTask(null);
      next = await getMemoryStatus({ startLoading: false });
      if (operationTokenRef.current !== token) {
        return;
      }
      const refreshed = { ...next, modelCached: Boolean(next.modelCached || result.cached) };
      setStatus(refreshed);
      if (!refreshed.modelCached) {
        throw new Error(t("api.memory.modelDownloadFailed"));
      }
    } catch (error) {
      if (operationTokenRef.current === token) {
        setTask(null);
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("api.memory.modelDownloadFailed"),
          title: t("api.memory.title"),
        });
      }
    } finally {
      operationInFlightRef.current = false;
      if (operationTokenRef.current === token) {
        setInstallingDependencyPackage(undefined);
        setChecking(false);
      }
    }
  };

  return (
    <section className="section memory-settings page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("api.memory.title")}</h2>
        <AsyncButton
          disabled={disabled || checkingEnable}
          icon={<DownloadCloud aria-hidden className="button__icon" />}
          loading={checking}
          onClick={() => void prepareMemory()}
        >
          {checking ? memoryBusyLabel(task, t, installingDependencyPackage) : memoryActionLabel(status, t)}
        </AsyncButton>
      </div>
      <p className="section__description">{t("api.memory.description")}</p>
      <label className="field-row">
        <span className="field-row__label">{t("api.memory.enabled")}</span>
        <span className="field-row__control">
          <Switch
            checked={draft.memory_auto_enabled}
            aria-busy={checkingEnable}
            disabled={disabled || checking || checkingEnable}
            id="memory-auto-enabled"
            onChange={(event) => void handleMemoryAutoChange(event)}
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
          {task ? (
            <TaskProgress labels={memoryTaskLabels(task, t, installingDependencyPackage)} logLimit={0} task={task} />
          ) : null}
        </span>
      </div>
    </section>
  );
}
