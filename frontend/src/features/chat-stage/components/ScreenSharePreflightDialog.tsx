import { AlertCircle, CheckCircle2, DownloadCloud, LoaderCircle, MonitorUp, RefreshCw } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type {
  PerceptionHealthProbe,
  PerceptionLocalServerStatus,
  PerceptionSetupStatus,
  PerceptionStatusResponse,
  TaskSnapshot,
} from "../../../shared/platform/types";
import { AsyncButton, Button, TaskProgress } from "../../../shared/ui";
import type { ScreenSharePreflightErrorKind, ScreenSharePreflightPhase } from "../hooks/useScreenSharePreflight";
import { ChatStageModal } from "./ChatStageModal";
import "./ScreenSharePreflightDialog.css";

export interface ScreenSharePreflightDialogProps {
  errorDetail: string;
  errorKind: ScreenSharePreflightErrorKind | null;
  health: PerceptionHealthProbe | null;
  installingPackage?: string;
  localServer: PerceptionLocalServerStatus | null;
  onCancel: () => void;
  onPrepareAndStart: () => void;
  onProceedToShare: () => void;
  onRetry: () => void;
  open: boolean;
  phase: ScreenSharePreflightPhase;
  setup: PerceptionSetupStatus | null;
  setupTask: TaskSnapshot | null;
  status: PerceptionStatusResponse | null;
}

type Translate = ReturnType<typeof useI18n>["t"];

function taskLabels(task: TaskSnapshot, t: Translate, dependencyPackage = "torch") {
  const isDependency = task.kind === "runtime-dependency-install";
  const phase =
    task.phase === "pip"
      ? t("api.perception.installingDependency", { packageName: dependencyPackage })
      : task.phase === "queued"
        ? t("api.perception.taskInProgress")
        : task.phase === "download"
          ? t("api.perception.downloading")
          : task.phase === "verify"
            ? t("api.perception.taskVerifying")
            : task.phase === "completed"
              ? t(isDependency ? "api.perception.dependencyInstalled" : "api.perception.modelCached")
              : task.phase === "failed"
                ? t(isDependency ? "api.perception.dependencyInstallFailed" : "api.perception.modelDownloadFailed")
                : undefined;
  const status =
    task.status === "running"
      ? t("api.perception.taskInProgress")
      : task.status === "succeeded"
        ? t(isDependency ? "api.perception.dependencyInstalled" : "api.perception.modelCached")
        : task.status === "failed"
          ? t(isDependency ? "api.perception.dependencyInstallFailed" : "api.perception.modelDownloadFailed")
          : undefined;
  return { phase, status };
}

function resolveErrorHeadline(
  errorKind: ScreenSharePreflightErrorKind | null,
  errorDetail: string,
  health: PerceptionHealthProbe | null,
  t: Translate,
): string {
  if (errorKind === "check_timeout") {
    return t("chat.perception.preflight.checkTimeout");
  }
  if (errorKind === "model_mismatch") {
    return t("api.perception.statusModelMismatch", {
      models: health?.models.length ? health.models.join(", ") : "—",
    });
  }
  if (errorKind === "unreachable") {
    return t("api.perception.statusUnreachable", { error: errorDetail || "—" });
  }
  if (errorKind === "server_failed") {
    return t("api.perception.serverFailed", { error: errorDetail || "—" });
  }
  if (errorKind === "missing_gguf") {
    return errorDetail || t("api.perception.setupModelMissing");
  }
  if (errorKind === "setup_error") {
    return errorDetail || t("api.perception.setupError");
  }
  return errorDetail || t("chat.perception.preflight.checkFailed");
}

function setupActionLabel(setup: PerceptionSetupStatus | null, t: Translate): string {
  if (setup?.status === "missing_dependency") {
    return t(
      setup.modelCached || setup.downloadable === false
        ? "api.perception.installDependency"
        : "api.perception.installAndDownload",
    );
  }
  return t("api.perception.downloadModel");
}

function installingBusyLabel(task: TaskSnapshot | null, t: Translate, installingPackage?: string): string {
  if (task?.phase === "pip" || installingPackage) {
    return t("api.perception.installingDependency", { packageName: installingPackage || "torch" });
  }
  if (task?.phase === "verify") {
    return t("api.perception.taskVerifying");
  }
  return t("api.perception.downloading");
}

export function ScreenSharePreflightDialog({
  errorDetail,
  errorKind,
  health,
  installingPackage,
  localServer,
  onCancel,
  onPrepareAndStart,
  onProceedToShare,
  onRetry,
  open,
  phase,
  setup,
  setupTask,
  status,
}: ScreenSharePreflightDialogProps) {
  const { t } = useI18n();
  if (!open) {
    return null;
  }

  let headline = t("chat.perception.preflight.checking");
  let description = t("chat.perception.preflight.checkingDesc");
  let tone: "busy" | "warn" | "ready" | "error" = "busy";
  let icon = <LoaderCircle aria-hidden className="screen-share-preflight__spinner" />;

  if (phase === "setup_needed") {
    tone = "warn";
    headline =
      setup?.status === "missing_dependency"
        ? t("api.perception.missingDependency", { packageName: setup.packageName || "torch" })
        : setup?.message || t("api.perception.setupModelMissing");
    description = t("chat.perception.preflight.setupNeededDesc");
    icon = <DownloadCloud aria-hidden className="screen-share-preflight__icon" />;
  } else if (phase === "installing") {
    tone = "busy";
    headline = installingBusyLabel(setupTask, t, installingPackage);
    description = t("chat.perception.preflight.setupNeededDesc");
  } else if (phase === "starting") {
    tone = "busy";
    headline = t("api.perception.serverStarting");
    description = t("chat.perception.preflight.startingDesc");
  } else if (phase === "ready") {
    tone = "ready";
    headline = t("chat.perception.preflight.readyTitle");
    description = t("chat.perception.preflight.readyDesc");
    icon = <CheckCircle2 aria-hidden className="screen-share-preflight__icon" />;
  } else if (phase === "error") {
    tone = "error";
    headline = resolveErrorHeadline(errorKind, errorDetail, health, t);
    description = t("chat.perception.preflight.errorHint");
    icon = <AlertCircle aria-hidden className="screen-share-preflight__icon" />;
  }

  const recentLogs =
    (phase === "starting" || phase === "error") && localServer?.logs.length ? localServer.logs.slice(-3) : [];
  const config = status?.config;

  return (
    <ChatStageModal
      backdropClassName="screen-share-preflight-backdrop"
      closeLabel={t("common.close")}
      dialogClassName="screen-share-preflight-dialog"
      dialogId="chat-screen-share-preflight"
      labelledBy="chat-screen-share-preflight-title"
      onClose={onCancel}
      open
      title={t("chat.perception.preflight.title")}
    >
      <div className="screen-share-preflight__body">
        <div aria-live="polite" className="screen-share-preflight__status" data-tone={tone} role="status">
          <span className="screen-share-preflight__status-icon">{icon}</span>
          <div className="screen-share-preflight__status-copy">
            <strong className="screen-share-preflight__headline">{headline}</strong>
            <p className="screen-share-preflight__description">{description}</p>
          </div>
        </div>

        {config ? (
          <dl className="screen-share-preflight__meta">
            <div className="screen-share-preflight__meta-row">
              <dt>{t("api.perception.model")}</dt>
              <dd>{config.model}</dd>
            </div>
            <div className="screen-share-preflight__meta-row">
              <dt>{t("api.perception.baseUrl")}</dt>
              <dd>{config.baseUrl}</dd>
            </div>
          </dl>
        ) : null}

        {phase === "installing" && setupTask ? (
          <TaskProgress labels={taskLabels(setupTask, t, installingPackage)} logLimit={3} task={setupTask} />
        ) : null}

        {recentLogs.length ? (
          <div className="screen-share-preflight__logs">
            <span className="screen-share-preflight__logs-label">{t("api.perception.serverLog")}</span>
            <pre className="screen-share-preflight__logs-body">{recentLogs.join("\n")}</pre>
          </div>
        ) : null}

        <div className="screen-share-preflight__actions">
          {phase === "checking" ? (
            <>
              <Button icon={<MonitorUp aria-hidden className="button__icon" />} onClick={onProceedToShare}>
                {t("chat.perception.preflight.skipAndShare")}
              </Button>
              <Button onClick={onCancel} variant="ghost">
                {t("common.cancel")}
              </Button>
            </>
          ) : null}

          {phase === "setup_needed" ? (
            <>
              <Button
                icon={<DownloadCloud aria-hidden className="button__icon" />}
                onClick={onPrepareAndStart}
                variant="primary"
              >
                {setupActionLabel(setup, t)}
              </Button>
              <Button icon={<MonitorUp aria-hidden className="button__icon" />} onClick={onProceedToShare}>
                {t("chat.perception.preflight.skipAndShare")}
              </Button>
              <Button onClick={onCancel} variant="ghost">
                {t("common.cancel")}
              </Button>
            </>
          ) : null}

          {phase === "installing" ? (
            <>
              <AsyncButton disabled loading variant="primary">
                {installingBusyLabel(setupTask, t, installingPackage)}
              </AsyncButton>
              <Button onClick={onCancel} variant="ghost">
                {t("common.cancel")}
              </Button>
            </>
          ) : null}

          {phase === "starting" ? (
            <>
              <AsyncButton disabled loading variant="primary">
                {t("api.perception.serverStarting")}
              </AsyncButton>
              <Button icon={<MonitorUp aria-hidden className="button__icon" />} onClick={onProceedToShare}>
                {t("chat.perception.preflight.shareWhileLoading")}
              </Button>
              <Button onClick={onCancel} variant="ghost">
                {t("common.cancel")}
              </Button>
            </>
          ) : null}

          {phase === "ready" ? (
            <>
              <Button
                icon={<MonitorUp aria-hidden className="button__icon" />}
                onClick={onProceedToShare}
                variant="primary"
              >
                {t("chat.perception.preflight.selectWindow")}
              </Button>
              <Button onClick={onCancel} variant="ghost">
                {t("common.cancel")}
              </Button>
            </>
          ) : null}

          {phase === "error" ? (
            <>
              <Button icon={<RefreshCw aria-hidden className="button__icon" />} onClick={onRetry} variant="primary">
                {t("chat.perception.preflight.retry")}
              </Button>
              <Button icon={<MonitorUp aria-hidden className="button__icon" />} onClick={onProceedToShare}>
                {t("chat.perception.preflight.skipAndShare")}
              </Button>
              <Button onClick={onCancel} variant="ghost">
                {t("common.cancel")}
              </Button>
            </>
          ) : null}
        </div>
      </div>
    </ChatStageModal>
  );
}
