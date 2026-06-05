import { useI18n } from "../i18n";
import type { DesktopRuntimeProgress } from "./desktopApi";

interface RuntimeProgressPanelProps {
  className?: string;
  progress: DesktopRuntimeProgress;
}

export function RuntimeProgressPanel({ className, progress }: RuntimeProgressPanelProps) {
  const { t } = useI18n();
  const hasTotal = typeof progress.total === "number" && progress.total > 0;
  const percent = hasTotal
    ? Math.max(0, Math.min(100, Math.round(((progress.downloaded ?? 0) / progress.total!) * 100)))
    : null;
  const progressClassName = ["desktop-runtime-progress", className].filter(Boolean).join(" ");
  const showTransferMeta =
    hasTotal &&
    ((progress.total ?? 0) > 1024 || (typeof progress.speedBytesPerSec === "number" && progress.speedBytesPerSec > 0));

  return (
    <div className={progressClassName} aria-live="polite">
      <div className="desktop-runtime-progress__header">
        <span>{progress.message || runtimeProgressPhaseLabel(progress.phase, t)}</span>
        {percent !== null ? <strong>{t("desktop.runtime.progressPercent", { percent })}</strong> : null}
      </div>
      <div
        aria-label={t("desktop.runtime.progressLabel")}
        aria-valuemax={hasTotal ? 100 : undefined}
        aria-valuemin={hasTotal ? 0 : undefined}
        aria-valuenow={percent ?? undefined}
        className="desktop-runtime-progress__bar"
        data-indeterminate={hasTotal ? undefined : "true"}
        role="progressbar"
      >
        <span style={percent !== null ? { width: `${percent}%` } : undefined} />
      </div>
      {showTransferMeta ? (
        <p className="desktop-runtime-progress__meta">
          {t("desktop.runtime.progressBytes", {
            downloaded: formatRuntimeBytes(progress.downloaded ?? 0),
            total: formatRuntimeBytes(progress.total ?? 0),
          })}
          {typeof progress.speedBytesPerSec === "number" && progress.speedBytesPerSec > 0
            ? ` · ${t("desktop.runtime.progressSpeed", { speed: formatRuntimeBytes(progress.speedBytesPerSec) })}`
            : ""}
        </p>
      ) : null}
    </div>
  );
}

function runtimeProgressPhaseLabel(phase: DesktopRuntimeProgress["phase"], t: ReturnType<typeof useI18n>["t"]) {
  const keys: Record<DesktopRuntimeProgress["phase"], Parameters<typeof t>[0]> = {
    checkingBridge: "desktop.runtime.phase.checkingBridge",
    installingDeps: "desktop.runtime.phase.installingDeps",
    probing: "desktop.runtime.phase.probing",
    ready: "desktop.runtime.phase.ready",
  };
  return t(keys[phase]);
}

function formatRuntimeBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const precision = unitIndex === 0 || size >= 100 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
}
