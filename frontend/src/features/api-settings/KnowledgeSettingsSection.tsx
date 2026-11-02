import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { DownloadCloud } from "lucide-react";

import { installMissingRuntimeDependency } from "../../entities/chat/repository";
import { getKnowledgeStatus } from "../../entities/knowledge/repository";
import type { ApiConfig } from "../../entities/config/types";
import { downloadModelAsset } from "../../entities/model-assets/repository";
import { isTauriDesktop, restartDesktopBridge } from "../../shared/desktop/desktopApi";
import { useI18n } from "../../shared/i18n";
import type { Mem0Status, TaskSnapshot } from "../../shared/platform/types";
import { AsyncButton, NumberInput, Switch, TaskProgress, useToast } from "../../shared/ui";
import { clampInt } from "./apiSettingsUtils";

interface KnowledgeSettingsSectionProps {
  disabled?: boolean;
  draft: ApiConfig;
  id?: string;
  onChange: (draft: ApiConfig) => void;
}

const KNOWLEDGE_EMBEDDING_ASSET = { assetId: "memory.embedding" } as const;

function dependencyPackageLabel(packageName: string | undefined, fallback: string) {
  const label = String(packageName || "")
    .replace(/(?:\[|[<>=!~]).*$/, "")
    .trim();
  return label || fallback;
}

function knowledgeStatusLabel(status: Mem0Status | null, t: ReturnType<typeof useI18n>["t"]) {
  if (!status) {
    return t("api.knowledge.statusUnknown");
  }
  if (status.status === "missing_dependency") {
    return t("api.knowledge.missingDependency", { packageName: status.packageName || "mem0ai" });
  }
  if (status.status === "error") {
    return t("api.knowledge.error");
  }
  if (status.status === "ready") {
    return t("api.knowledge.setupReady");
  }
  if (status.status === "loading") {
    return status.modelCached ? t("api.knowledge.loadingCached") : t("api.knowledge.downloading");
  }
  return status.modelCached ? t("api.knowledge.setupReady") : t("api.knowledge.setupModelMissing");
}

function knowledgeActionLabel(status: Mem0Status | null, t: ReturnType<typeof useI18n>["t"]) {
  if (!status) {
    return t("api.knowledge.checkModel");
  }
  if (status.status === "missing_dependency") {
    return t("api.knowledge.installDependency");
  }
  if (status.status === "error" || status.status === "loading" || status.modelCached) {
    return t("api.knowledge.recheckModel");
  }
  return t("api.knowledge.downloadModel");
}

function knowledgeTaskLabels(task: TaskSnapshot, t: ReturnType<typeof useI18n>["t"], dependencyPackage = "mem0ai") {
  const dependencyTask = task.kind === "runtime-dependency-install";
  const phase =
    task.phase === "pip"
      ? t("api.knowledge.installingDependency", { packageName: dependencyPackage })
      : task.phase === "queued"
        ? t("api.knowledge.taskInProgress")
        : task.phase === "download"
          ? t("api.knowledge.downloading")
          : task.phase === "verify"
            ? t("api.knowledge.taskVerifying")
            : task.phase === "completed"
              ? t(dependencyTask ? "api.knowledge.dependencyInstalled" : "api.knowledge.modelCached")
              : task.phase === "failed"
                ? t(dependencyTask ? "api.knowledge.dependencyInstallFailed" : "api.knowledge.modelDownloadFailed")
                : undefined;
  const status =
    task.status === "running"
      ? t("api.knowledge.taskInProgress")
      : task.status === "succeeded"
        ? t(dependencyTask ? "api.knowledge.dependencyInstalled" : "api.knowledge.modelCached")
        : task.status === "failed"
          ? t(dependencyTask ? "api.knowledge.dependencyInstallFailed" : "api.knowledge.modelDownloadFailed")
          : undefined;
  return { phase, status };
}

function knowledgeBusyLabel(task: TaskSnapshot | null, t: ReturnType<typeof useI18n>["t"], dependencyPackage?: string) {
  if (!task) {
    return dependencyPackage
      ? t("api.knowledge.installingDependency", { packageName: dependencyPackage })
      : t("api.knowledge.checking");
  }
  return knowledgeTaskLabels(task, t, dependencyPackage).phase || t("api.knowledge.checking");
}

export function KnowledgeSettingsSection({ disabled = false, draft, id, onChange }: KnowledgeSettingsSectionProps) {
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
    void getKnowledgeStatus({ startLoading: false })
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

  const handleKnowledgeAutoChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const enabled = event.currentTarget.checked;
    if (!enabled) {
      patch({ knowledge_enabled: false });
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
      const next = await getKnowledgeStatus({ startLoading: false });
      if (operationTokenRef.current !== token) {
        return;
      }
      setStatus(next);
      setTask(next.task ?? null);

      if (next.status === "error") {
        showToast({ kind: "error", message: t("api.knowledge.error"), title: t("api.knowledge.title") });
        return;
      }
      if (next.status === "missing_dependency" || !next.modelCached) {
        showToast({
          kind: "info",
          message: t("api.knowledge.enableRequiresSetup"),
          title: t("api.knowledge.title"),
        });
        return;
      }
      patch({ knowledge_enabled: true });
    } catch {
      if (operationTokenRef.current === token) {
        showToast({ kind: "error", message: t("api.knowledge.error"), title: t("api.knowledge.title") });
      }
    } finally {
      operationInFlightRef.current = false;
      if (operationTokenRef.current === token) {
        setCheckingEnable(false);
      }
    }
  };

  const prepareKnowledge = async () => {
    if (operationInFlightRef.current) {
      return;
    }
    operationInFlightRef.current = true;
    const token = operationTokenRef.current + 1;
    operationTokenRef.current = token;
    setChecking(true);
    setTask(null);
    try {
      let next = await getKnowledgeStatus({ startLoading: false });
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
        next = await getKnowledgeStatus({ startLoading: false });
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
                ? t("api.knowledge.missingDependency", { packageName: next.packageName || "mem0ai" })
                : t("api.knowledge.error"),
            title: t("api.knowledge.title"),
          });
        }
        return;
      }
      if (next.modelCached) {
        return;
      }

      const result = await downloadModelAsset(KNOWLEDGE_EMBEDDING_ASSET, {
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
      next = await getKnowledgeStatus({ startLoading: false });
      if (operationTokenRef.current !== token) {
        return;
      }
      const refreshed = { ...next, modelCached: Boolean(next.modelCached || result.cached) };
      setStatus(refreshed);
      if (!refreshed.modelCached) {
        throw new Error(t("api.knowledge.modelDownloadFailed"));
      }
    } catch (error) {
      if (operationTokenRef.current === token) {
        setTask(null);
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("api.knowledge.modelDownloadFailed"),
          title: t("api.knowledge.title"),
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
        <h2 className="section__title">{t("api.knowledge.title")}</h2>
        <AsyncButton
          disabled={disabled || checkingEnable}
          icon={<DownloadCloud aria-hidden className="button__icon" />}
          loading={checking}
          onClick={() => void prepareKnowledge()}
        >
          {checking ? knowledgeBusyLabel(task, t, installingDependencyPackage) : knowledgeActionLabel(status, t)}
        </AsyncButton>
      </div>
      <p className="section__description">{t("api.knowledge.description")}</p>
      <label className="field-row">
        <span className="field-row__label">{t("api.knowledge.enabled")}</span>
        <span className="field-row__control">
          <Switch
            checked={draft.knowledge_enabled}
            aria-busy={checkingEnable}
            disabled={disabled || checking || checkingEnable}
            id="knowledge-enabled"
            onChange={(event) => void handleKnowledgeAutoChange(event)}
          />
        </span>
      </label>
      <label className="field-row">
        <span className="field-row__label">{t("api.knowledge.searchLimit")}</span>
        <span className="field-row__control">
          <NumberInput
            disabled={disabled || !draft.knowledge_enabled}
            max={20}
            min={1}
            onChange={(event) => patch({ knowledge_search_limit: clampInt(event.currentTarget.value, 5, 1, 20) })}
            step={1}
            value={draft.knowledge_search_limit}
          />
          <span className="field-row__help">{t("api.knowledge.searchLimitHelp")}</span>
        </span>
      </label>
      <div className="field-row" aria-live="polite">
        <span className="field-row__label">{t("api.knowledge.modelStatus")}</span>
        <span className="field-row__control">
          <span className="memory-settings__status-value">{knowledgeStatusLabel(status, t)}</span>
          {task ? (
            <TaskProgress labels={knowledgeTaskLabels(task, t, installingDependencyPackage)} logLimit={0} task={task} />
          ) : null}
        </span>
      </div>
    </section>
  );
}
