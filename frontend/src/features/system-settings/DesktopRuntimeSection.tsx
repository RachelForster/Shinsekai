import { useCallback, useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";

import {
  browseDesktopFiles,
  chooseDesktopRuntimePython,
  isTauriDesktop,
  onDesktopRuntimeProgress,
  repairDesktopRuntime,
  scanDesktopRuntime,
  selectDesktopRuntime,
  type DesktopRuntimeCandidate,
  type DesktopRuntimeCandidateStatus,
  type DesktopRuntimeProgress,
  type DesktopRuntimeRepairAction,
  type DesktopRuntimeState,
} from "../../shared/desktop/desktopApi";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, FilePicker } from "../../shared/ui";

function runtimeCandidateStatusLabel(status: DesktopRuntimeCandidateStatus, t: ReturnType<typeof useI18n>["t"]) {
  const keys: Record<DesktopRuntimeCandidateStatus, Parameters<typeof t>[0]> = {
    brokenBridge: "desktop.runtime.status.brokenBridge",
    brokenPython: "desktop.runtime.status.brokenPython",
    missingCoreDeps: "desktop.runtime.status.missingCoreDeps",
    missingOptionalDeps: "desktop.runtime.status.missingOptionalDeps",
    ready: "desktop.runtime.status.ready",
    unsupportedVersion: "desktop.runtime.status.unsupportedVersion",
    wrongArchitecture: "desktop.runtime.status.wrongArchitecture",
  };
  return t(keys[status]);
}

function progressLabel(progress: DesktopRuntimeProgress, t: ReturnType<typeof useI18n>["t"]) {
  if (progress.message) {
    return progress.message;
  }
  const keys: Record<DesktopRuntimeProgress["phase"], Parameters<typeof t>[0]> = {
    checkingBridge: "desktop.runtime.phase.checkingBridge",
    installingDeps: "desktop.runtime.phase.installingDeps",
    probing: "desktop.runtime.phase.probing",
    ready: "desktop.runtime.phase.ready",
  };
  return t(keys[progress.phase]);
}

function candidateActions(candidate: DesktopRuntimeCandidate) {
  return new Set<DesktopRuntimeRepairAction>(candidate.repairActions);
}

export function DesktopRuntimeSection() {
  const desktop = isTauriDesktop();
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<DesktopRuntimeState | null>(null);
  const [runtimeProgress, setRuntimeProgress] = useState<DesktopRuntimeProgress | null>(null);
  const [pythonPath, setPythonPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runRuntimeAction = useCallback(async (action: () => Promise<DesktopRuntimeState>) => {
    setBusy(true);
    setError(null);
    try {
      setRuntime(await action());
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }, []);

  const refresh = useCallback(() => runRuntimeAction(scanDesktopRuntime), [runRuntimeAction]);

  useEffect(() => {
    if (!desktop) {
      return;
    }
    void refresh();
  }, [desktop, refresh]);

  useEffect(() => {
    if (!desktop) {
      return;
    }
    let stopped = false;
    let dispose: (() => void) | null = null;
    void onDesktopRuntimeProgress((progress) => {
      if (!stopped) {
        setRuntimeProgress(progress);
      }
    }).then((unlisten) => {
      if (stopped) {
        unlisten();
        return;
      }
      dispose = unlisten;
    });
    return () => {
      stopped = true;
      dispose?.();
    };
  }, [desktop]);

  if (!desktop) {
    return null;
  }

  const choosePython = () => {
    const path = pythonPath.trim();
    if (!path) {
      return;
    }
    void runRuntimeAction(() => chooseDesktopRuntimePython(path));
  };

  return (
    <section className="section desktop-runtime-settings">
      <div className="section__header">
        <div>
          <h2 className="section__title">{t("system.runtime.title")}</h2>
          <p className="section__description">{t("system.runtime.description")}</p>
        </div>
        <div className="page__actions">
          <AsyncButton
            icon={<RefreshCcw aria-hidden className="button__icon" />}
            loading={busy}
            onClick={refresh}
            variant="ghost"
          >
            {t("system.runtime.scan")}
          </AsyncButton>
        </div>
      </div>
      {runtime?.message || error ? (
        <p className="desktop-runtime-settings__message">{error ?? runtime?.message}</p>
      ) : null}
      {runtimeProgress ? (
        <p className="desktop-runtime-settings__progress">{progressLabel(runtimeProgress, t)}</p>
      ) : null}
      <div className="desktop-runtime-settings__list">
        {runtime?.candidates?.length ? (
          runtime.candidates.map((candidate) => {
            const actions = candidateActions(candidate);
            return (
              <article
                className="desktop-runtime-settings__candidate"
                data-status={candidate.status}
                key={candidate.id}
              >
                <div className="desktop-runtime-settings__candidate-main">
                  <div>
                    <h3>{candidate.label}</h3>
                    <p>{candidate.version || candidate.kind}</p>
                  </div>
                  <span>{runtimeCandidateStatusLabel(candidate.status, t)}</span>
                </div>
                {candidate.pythonVersion ? (
                  <p>
                    {t("desktop.runtime.candidatePythonVersion")}: {candidate.pythonVersion}
                  </p>
                ) : null}
                {candidate.path ? <code>{candidate.path}</code> : null}
                {candidate.message ? <p>{candidate.message}</p> : null}
                {[...candidate.missingPackages, ...candidate.missingImports].length ? (
                  <p>
                    {t("desktop.runtime.candidateMissing")}:{" "}
                    {[...candidate.missingPackages, ...candidate.missingImports].join(", ")}
                  </p>
                ) : null}
                {candidate.warnings.length ? (
                  <p>
                    {t("desktop.runtime.candidateWarnings")}: {candidate.warnings.join(" ")}
                  </p>
                ) : null}
                <div className="desktop-runtime-settings__candidate-actions">
                  {candidate.status === "ready" ? (
                    <Button
                      disabled={busy || candidate.selected}
                      onClick={() => void runRuntimeAction(() => selectDesktopRuntime(candidate.id))}
                    >
                      {candidate.selected ? t("system.runtime.current") : t("desktop.runtime.useCandidate")}
                    </Button>
                  ) : null}
                  {actions.has("createManagedVenv") ? (
                    <Button
                      disabled={busy}
                      onClick={() =>
                        void runRuntimeAction(() => repairDesktopRuntime(candidate.id, "createManagedVenv"))
                      }
                      variant="primary"
                    >
                      {t("desktop.runtime.createVenvButton")}
                    </Button>
                  ) : null}
                  {actions.has("installRuntimeDeps") ? (
                    <Button
                      disabled={busy}
                      onClick={() =>
                        void runRuntimeAction(() => repairDesktopRuntime(candidate.id, "installRuntimeDeps"))
                      }
                      variant="primary"
                    >
                      {t("desktop.runtime.installDepsButton")}
                    </Button>
                  ) : null}
                </div>
              </article>
            );
          })
        ) : (
          <p className="desktop-runtime-settings__empty">{t("system.runtime.noCandidates")}</p>
        )}
      </div>
      <div className="desktop-runtime-settings__import">
        <label htmlFor="system-runtime-python">{t("desktop.runtime.pythonPathLabel")}</label>
        <div className="desktop-runtime-settings__import-row">
          <FilePicker
            disabled={busy}
            id="system-runtime-python"
            onChange={(event) => setPythonPath(event.currentTarget.value)}
            onPathChange={setPythonPath}
            pickLabel={t("desktop.runtime.choosePythonButton")}
            pickerBrowse={browseDesktopFiles}
            pickerMode="path"
            pickerTitle={t("desktop.runtime.pythonPathLabel")}
            placeholder={t("desktop.runtime.pythonPathPlaceholder")}
            value={pythonPath}
          />
          <Button disabled={busy || !pythonPath.trim()} onClick={choosePython}>
            {t("desktop.runtime.usePythonButton")}
          </Button>
        </div>
      </div>
    </section>
  );
}
