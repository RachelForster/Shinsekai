import { useEffect, useState } from "react";
import { DownloadCloud } from "lucide-react";

import {
  checkDesktopUpdate,
  desktopRestartErrorMessage,
  installDesktopUpdate,
  isTauriDesktop,
  onDesktopUpdateProgress,
  type DesktopUpdate,
  type DesktopUpdateProgress,
} from "../../shared/desktop/desktopApi";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, Dialog } from "../../shared/ui";

type StartupUpdateStatus = "idle" | "available" | "downloading" | "installing" | "restartRequired" | "error";

let startupUpdateCheckStarted = false;

export function StartupUpdatePrompt() {
  const { t } = useI18n();
  const [status, setStatus] = useState<StartupUpdateStatus>("idle");
  const [update, setUpdate] = useState<DesktopUpdate | null>(null);
  const [progress, setProgress] = useState<DesktopUpdateProgress | null>(null);
  const [error, setError] = useState("");

  const busy = status === "downloading" || status === "installing";
  const open = Boolean(update) || busy || status === "restartRequired" || status === "error";

  useEffect(() => {
    if (!isTauriDesktop() || startupUpdateCheckStarted) {
      return;
    }

    startupUpdateCheckStarted = true;
    let cancelled = false;

    void checkDesktopUpdate()
      .then((nextUpdate) => {
        if (cancelled || !nextUpdate) {
          return;
        }
        setUpdate(nextUpdate);
        setStatus("available");
      })
      .catch((checkError) => {
        console.warn("[desktop-update] startup update check failed", checkError);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isTauriDesktop() || !open) {
      return;
    }

    let cancelled = false;
    let unlisten: (() => void) | null = null;

    void onDesktopUpdateProgress((nextProgress) => {
      setProgress(nextProgress);
      if (nextProgress.event === "started" || nextProgress.event === "progress") {
        setStatus("downloading");
      } else if (nextProgress.event === "finished") {
        setStatus("installing");
      }
    })
      .then((dispose) => {
        if (cancelled) {
          dispose();
          return;
        }
        unlisten = dispose;
      })
      .catch((listenError) => {
        if (!cancelled) {
          setError(desktopUpdateError(listenError, t("plugin.desktopUpdate.checkFailed")));
          setStatus("error");
        }
      });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [open, t]);

  const close = () => {
    if (busy) {
      return;
    }
    setStatus("idle");
    setUpdate(null);
    setProgress(null);
    setError("");
  };

  const install = async () => {
    setStatus("downloading");
    setError("");
    setProgress({ contentLength: null, downloaded: 0, event: "started" });
    try {
      await installDesktopUpdate();
      setStatus("restartRequired");
    } catch (installError) {
      setError(desktopUpdateError(installError, t("plugin.desktopUpdate.installFailed")));
      setStatus("error");
    }
  };

  const busyLabel =
    status === "installing" ? t("plugin.desktopUpdate.installing") : t("plugin.desktopUpdate.downloading");

  return (
    <Dialog
      closeLabel={t("common.close")}
      footer={
        status === "available" ? (
          <>
            <Button onClick={close}>{t("common.cancel")}</Button>
            <AsyncButton
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              onClick={() => void install()}
              variant="primary"
            >
              {t("plugin.desktopUpdate.installRestart")}
            </AsyncButton>
          </>
        ) : busy ? (
          <Button disabled>{busyLabel}</Button>
        ) : (
          <Button onClick={close} variant="primary">
            {t("common.confirm")}
          </Button>
        )
      }
      onClose={close}
      open={open}
      title={t("plugin.desktopUpdate.title")}
    >
      <div className="startup-update">
        {update ? (
          <div className="startup-update__summary">
            <strong>{t("plugin.desktopUpdate.available", { version: update.version })}</strong>
            {update.date ? (
              <span className="inline-status">{t("plugin.desktopUpdate.releaseDate", { date: update.date })}</span>
            ) : null}
            {update.body ? (
              <div className="startup-update__notes">
                <span className="field-row__label">{t("plugin.desktopUpdate.releaseNotes")}</span>
                <p>{update.body}</p>
              </div>
            ) : null}
          </div>
        ) : null}
        {busy ? (
          <StartupUpdateProgressView
            label={busyLabel}
            progress={progress}
            unknownSizeLabel={t("plugin.desktopUpdate.unknownSize")}
          />
        ) : null}
        {status === "restartRequired" ? (
          <p className="startup-update__message">{t("plugin.desktopUpdate.restartRequiredBody")}</p>
        ) : null}
        {status === "error" ? (
          <p className="field-row__help" role="alert">
            {error || t("plugin.desktopUpdate.installFailed")}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}

function StartupUpdateProgressView({
  label,
  progress,
  unknownSizeLabel,
}: {
  label: string;
  progress: DesktopUpdateProgress | null;
  unknownSizeLabel: string;
}) {
  const percent = updateProgressPercent(progress);
  const detail = updateProgressLabel(progress, unknownSizeLabel);
  return (
    <div className="startup-update-progress">
      <div className="startup-update-progress__header">
        <span>{label}</span>
        <span>{percent == null ? "" : `${percent}%`}</span>
      </div>
      <div
        aria-label={label}
        aria-valuemax={percent == null ? undefined : 100}
        aria-valuemin={percent == null ? undefined : 0}
        aria-valuenow={percent ?? undefined}
        className="startup-update-progress__track"
        role="progressbar"
      >
        <span
          className="startup-update-progress__bar"
          data-indeterminate={percent == null || undefined}
          style={{ width: `${percent ?? 100}%` }}
        />
      </div>
      {detail ? <span className="inline-status">{detail}</span> : null}
    </div>
  );
}

function updateProgressPercent(progress: DesktopUpdateProgress | null) {
  const contentLength = progress?.contentLength ?? 0;
  if (!progress || contentLength <= 0) {
    return null;
  }
  return Math.min(100, Math.max(0, Math.round((progress.downloaded / contentLength) * 100)));
}

function updateProgressLabel(progress: DesktopUpdateProgress | null, unknownSizeLabel: string) {
  if (!progress) {
    return "";
  }
  const downloaded = formatUpdateBytes(progress.downloaded);
  if (!progress.contentLength || progress.contentLength <= 0) {
    return `${downloaded} / ${unknownSizeLabel}`;
  }
  return `${downloaded} / ${formatUpdateBytes(progress.contentLength)}`;
}

function formatUpdateBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"] as const;
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`;
}

function desktopUpdateError(error: unknown, fallback: string) {
  const rawMessage = desktopRestartErrorMessage(error).trim();
  if (!rawMessage) {
    return fallback;
  }
  return `${fallback} ${rawMessage}`;
}
