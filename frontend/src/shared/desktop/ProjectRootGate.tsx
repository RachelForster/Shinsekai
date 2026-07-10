import { useCallback, useEffect, useState, type ReactNode } from "react";
import { FolderCheck } from "lucide-react";

import {
  closeDesktopWindow,
  desktopRestartErrorMessage,
  getDesktopProjectRootStatus,
  isTauriDesktop,
  restartDesktopApp,
  selectDesktopProjectRoot,
  type DesktopProjectRootStatus,
} from "./desktopApi";
import { useI18n } from "../i18n";
import { Button, Dialog } from "../ui";

export function ProjectRootGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(() => !isTauriDesktop());
  const markReady = useCallback(() => setReady(true), []);

  if (ready) {
    return <>{children}</>;
  }

  return <ProjectRootPrompt onResolved={markReady} />;
}

export function ProjectRootPrompt({ onResolved }: { onResolved?: () => void }) {
  const { t } = useI18n();
  const [status, setStatus] = useState<DesktopProjectRootStatus | null>(null);
  const [selectedPath, setSelectedPath] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [statusError, setStatusError] = useState("");
  const [statusAttempt, setStatusAttempt] = useState(0);

  useEffect(() => {
    if (!isTauriDesktop()) {
      onResolved?.();
      return;
    }

    let cancelled = false;
    setStatusError("");
    void getDesktopProjectRootStatus()
      .then((nextStatus) => {
        if (!cancelled) {
          setStatus(nextStatus);
          if (!nextStatus.requiresSelection) {
            onResolved?.();
          }
        }
      })
      .catch((statusError) => {
        console.warn("[project-root] unable to read migration status", statusError);
        if (!cancelled) {
          setStatusError(desktopRestartErrorMessage(statusError));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [onResolved, statusAttempt]);

  if (statusError) {
    return (
      <Dialog
        dismissible={false}
        footer={
          <>
            <Button onClick={() => void closeDesktopWindow()}>{t("app.projectRoot.exit")}</Button>
            <Button onClick={() => setStatusAttempt((attempt) => attempt + 1)} variant="primary">
              {t("app.projectRoot.retry")}
            </Button>
          </>
        }
        onClose={() => undefined}
        open
        title={t("app.projectRoot.title")}
      >
        <p className="field-row__help" role="alert">
          {t("app.projectRoot.statusError", { message: statusError })}
        </p>
      </Dialog>
    );
  }

  if (!status?.requiresSelection) {
    return null;
  }

  const hasSelectableCandidate = status.candidates.some((candidate) => candidate.selectable);

  const applySelection = async () => {
    if (!selectedPath || saving) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      await selectDesktopProjectRoot(selectedPath);
      await restartDesktopApp();
    } catch (selectionError) {
      setError(
        t("app.projectRoot.error", {
          message: desktopRestartErrorMessage(selectionError),
        }),
      );
      setSaving(false);
    }
  };

  return (
    <Dialog
      className="project-root-prompt"
      dismissible={false}
      footer={
        <>
          <Button disabled={saving} onClick={() => void closeDesktopWindow()}>
            {t("app.projectRoot.exit")}
          </Button>
          <Button
            disabled={!selectedPath}
            icon={<FolderCheck aria-hidden className="button__icon" />}
            loading={saving}
            onClick={() => void applySelection()}
            variant="primary"
          >
            {saving ? t("app.projectRoot.restarting") : t("app.projectRoot.select")}
          </Button>
        </>
      }
      onClose={() => undefined}
      open
      title={t("app.projectRoot.title")}
    >
      <div className="project-root-prompt__content">
        <p>{t("app.projectRoot.body")}</p>
        <fieldset className="project-root-prompt__choices">
          <legend>{t("app.projectRoot.choose")}</legend>
          {status.candidates.map((candidate) => (
            <label
              className={[
                "project-root-prompt__choice",
                selectedPath === candidate.path ? "project-root-prompt__choice--selected" : "",
                !candidate.selectable ? "project-root-prompt__choice--disabled" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={candidate.path}
            >
              <input
                checked={selectedPath === candidate.path}
                disabled={saving || !candidate.selectable}
                name="project-root"
                onChange={() => setSelectedPath(candidate.path)}
                type="radio"
                value={candidate.path}
              />
              <span className="project-root-prompt__choice-body">
                <code>{candidate.path}</code>
                <span className="project-root-prompt__badges">
                  {candidate.hasProjectData ? <span>{t("app.projectRoot.dataDetected")}</span> : null}
                  {candidate.path === status.currentPath ? <span>{t("app.projectRoot.current")}</span> : null}
                  {!candidate.selectable ? <span>{t("app.projectRoot.unavailable")}</span> : null}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        <p className="project-root-prompt__notice">{t("app.projectRoot.notice")}</p>
        {!hasSelectableCandidate ? (
          <p className="field-row__help" role="alert">
            {t("app.projectRoot.blocked")}
          </p>
        ) : null}
        {error ? (
          <p className="field-row__help" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
