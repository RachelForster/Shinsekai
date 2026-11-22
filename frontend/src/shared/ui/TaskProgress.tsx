import { useOptionalI18n, type MessageKey, type TranslateFn } from "../i18n";
import "./TaskProgress.css";

interface TaskProgressSnapshot {
  completedItems?: number;
  dependencyInstallStatus?: string;
  errorUserMessage?: string;
  fallbackAllowed?: boolean;
  installSource?: string;
  installSourceLabel?: string;
  logs?: readonly string[];
  message?: string;
  notice?: string;
  noticeKind?: "error" | "info" | "warning";
  packageSha256?: string;
  packageSource?: string;
  packageStatus?: string;
  packageUrl?: string;
  phase: string;
  progress?: number | null;
  status: string;
  totalItems?: number;
}

interface TaskProgressProps {
  compact?: boolean;
  labels?: {
    message?: string;
    phase?: string;
    status?: string;
  };
  logLimit?: number;
  task: TaskProgressSnapshot | null;
}

function taskPercent(progress: number | null | undefined) {
  if (progress == null) {
    return null;
  }
  return Math.min(100, Math.max(0, Math.round(progress * 100)));
}

const phaseLabelKeys: Record<string, MessageKey> = {
  annotating: "task.phase.annotating",
  cancelled: "task.phase.cancelled",
  completed: "task.phase.completed",
  crop: "task.phase.crop",
  download: "task.phase.download",
  extract: "task.phase.extract",
  failed: "task.phase.failed",
  generate: "task.phase.generate",
  install: "task.phase.install",
  installingDeps: "task.phase.installingDeps",
  "loading-model": "task.phase.loading-model",
  manifest: "task.phase.manifest",
  merge: "task.phase.merge",
  pipeline: "task.phase.pipeline",
  pip: "task.phase.pip",
  probe: "task.phase.probe",
  prompt: "task.phase.prompt",
  queued: "task.phase.queued",
  reload: "task.phase.reload",
  "remove-background": "task.phase.remove-background",
  registry: "task.phase.registry",
  run: "task.phase.run",
  running: "task.phase.running",
  verify: "task.phase.verify",
  write: "task.phase.write",
};

const packageStatusLabelKeys: Record<string, MessageKey> = {
  checking: "task.packageStatus.checking",
  downloading: "task.packageStatus.downloading",
  existing: "task.packageStatus.existing",
  failed: "task.packageStatus.failed",
  fallback: "task.packageStatus.fallback",
  installed: "task.packageStatus.installed",
  pending: "task.packageStatus.pending",
  verified: "task.packageStatus.verified",
};

const dependencyStatusLabelKeys: Record<string, MessageKey> = {
  "not-required": "task.depStatus.not-required",
  pending: "task.depStatus.pending",
  pip_conflict: "task.depStatus.pip_conflict",
  pip_exception: "task.depStatus.pip_exception",
  pip_failed: "task.depStatus.pip_failed",
  pip_ok: "task.depStatus.pip_ok",
  pip_skip_no_requirements: "task.depStatus.pip_skip_no_requirements",
  pip_timeout: "task.depStatus.pip_timeout",
  running: "task.depStatus.running",
};

const installSourceLabelKeys: Record<string, MessageKey> = {
  github: "task.installSource.github",
  local: "task.installSource.local",
  package: "task.installSource.package",
  registry: "task.installSource.registry",
  repository: "task.installSource.repository",
  source: "task.installSource.source",
};

function statusLabel(value: string | undefined, keys: Record<string, MessageKey>, t: TranslateFn) {
  const code = (value ?? "").trim();
  if (!code) {
    return "";
  }
  const messageKey = keys[code];
  return messageKey ? t(messageKey) : code;
}

function compactSha(value: string | undefined) {
  const sha = (value ?? "").trim();
  if (!sha) {
    return "";
  }
  return sha.length > 16 ? `${sha.slice(0, 12)}...` : sha;
}

export function TaskProgress({ compact = false, labels, logLimit = 6, task }: TaskProgressProps) {
  const { t } = useOptionalI18n();

  if (!task) {
    return null;
  }

  const percent = taskPercent(task.progress);
  const itemProgress =
    typeof task.completedItems === "number" && typeof task.totalItems === "number"
      ? `${task.completedItems}/${task.totalItems}`
      : "";
  const logs = logLimit > 0 ? (task.logs ?? []).slice(-logLimit) : [];
  const notice = task.notice || (task.status === "failed" ? task.errorUserMessage : "");
  const noticeKind = task.noticeKind || (task.status === "failed" ? "error" : "info");
  const phaseKey = phaseLabelKeys[task.phase];
  const displayPhase = labels?.phase ?? (phaseKey ? t(phaseKey) : task.phase);
  const message = labels?.message ?? task.message ?? labels?.status ?? task.status;
  const showMessage = message !== notice && message !== displayPhase;
  const sourceLabel = task.installSourceLabel || statusLabel(task.installSource, installSourceLabelKeys, t);
  const packageLabel = statusLabel(task.packageStatus, packageStatusLabelKeys, t);
  const dependencyLabel = statusLabel(task.dependencyInstallStatus, dependencyStatusLabelKeys, t);
  const packageSourceLabel = task.packageSource ? task.packageSource.toUpperCase() : "";
  const packageDetail = [packageLabel, packageSourceLabel].filter(Boolean).join(" / ");
  const packageSha = compactSha(task.packageSha256);
  const installDetails = [
    sourceLabel ? { label: t("task.detail.source"), value: sourceLabel } : null,
    packageDetail ? { label: t("task.detail.package"), value: packageDetail } : null,
    dependencyLabel ? { label: t("task.detail.dependency"), value: dependencyLabel } : null,
    packageSha ? { label: "SHA256", value: packageSha } : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item));

  return (
    <div className={`task-progress${compact ? " task-progress--compact" : ""}`} role="status" aria-live="polite">
      <div className="task-progress__meta">
        {displayPhase ? <strong>{displayPhase}</strong> : null}
        <span>
          {[itemProgress, percent == null ? (labels?.status ?? task.status) : `${percent}%`]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      {percent == null ? null : (
        <div className="task-progress__track" aria-hidden>
          <span className="task-progress__fill" style={{ width: `${percent}%` }} />
        </div>
      )}
      {showMessage ? (
        <div className="task-progress__message" title={compact ? message : undefined}>
          {message}
        </div>
      ) : null}
      {notice ? (
        <div
          className={`task-progress__notice task-progress__notice--${noticeKind}`}
          title={compact ? notice : undefined}
        >
          {notice}
          {task.fallbackAllowed && task.status === "failed" ? t("task.detail.retryLaterSuffix") : ""}
        </div>
      ) : null}
      {installDetails.length ? (
        <dl className="task-progress__details" aria-label={t("task.detail.ariaLabel")}>
          {installDetails.map((item) => (
            <div className="task-progress__detail" key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {logs.length ? <pre className="task-progress__log">{logs.join("\n")}</pre> : null}
    </div>
  );
}
