import { useCallback, useEffect, useState } from "react";
import { DownloadCloud, RefreshCcw } from "lucide-react";

import {
  installDesktopRuntimeProfile,
  isTauriDesktop,
  onDesktopRuntimeProgress,
  repairDesktopRuntime,
  scanDesktopRuntime,
  selectDesktopRuntime,
  type DesktopRuntimeCandidate,
  type DesktopRuntimeCandidateStatus,
  type DesktopRuntimeProgress,
  type DesktopRuntimeProfile,
  type DesktopRuntimeRepairAction,
  type DesktopRuntimeState,
} from "../../shared/desktop/desktopApi";
import { RuntimeProgressPanel } from "../../shared/desktop/RuntimeProgressPanel";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button } from "../../shared/ui";

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

function candidateActions(candidate: DesktopRuntimeCandidate) {
  return new Set<DesktopRuntimeRepairAction>(candidate.repairActions);
}

export function DesktopRuntimeSection() {
  const desktop = isTauriDesktop();
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<DesktopRuntimeState | null>(null);
  const [runtimeProgress, setRuntimeProgress] = useState<DesktopRuntimeProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeProfile, setActiveProfile] = useState<DesktopRuntimeProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runRuntimeAction = useCallback(
    async (action: () => Promise<DesktopRuntimeState>, profile?: DesktopRuntimeProfile) => {
      setBusy(true);
      setActiveProfile(profile ?? null);
      setError(null);
      try {
        setRuntime(await action());
      } catch (error) {
        setError(error instanceof Error ? error.message : String(error));
      } finally {
        setActiveProfile(null);
        setBusy(false);
      }
    },
    [],
  );

  const refresh = useCallback(() => runRuntimeAction(scanDesktopRuntime), [runRuntimeAction]);
  const installRuntimeProfile = useCallback(
    (profile: DesktopRuntimeProfile) => runRuntimeAction(() => installDesktopRuntimeProfile(profile), profile),
    [runRuntimeAction],
  );

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

  const currentCandidateId =
    runtime?.selectedCandidateId ?? runtime?.candidates.find((candidate) => candidate.selected)?.id;
  const visibleCandidates = currentCandidateId
    ? (runtime?.candidates ?? []).filter((candidate) => candidate.id === currentCandidateId)
    : (runtime?.candidates ?? []);

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
      {runtimeProgress ? <RuntimeProgressPanel progress={runtimeProgress} /> : null}
      <div className="desktop-runtime-settings__optional">
        <div>
          <h3>{t("system.runtime.optionalTitle")}</h3>
          <p>{t("system.runtime.optionalDescription")}</p>
        </div>
        <div className="desktop-runtime-settings__optional-actions">
          <AsyncButton
            disabled={busy}
            icon={<DownloadCloud aria-hidden className="button__icon" />}
            loading={activeProfile === "media"}
            onClick={() => void installRuntimeProfile("media")}
            variant="ghost"
          >
            {t("system.runtime.installMedia")}
          </AsyncButton>
          <AsyncButton
            disabled={busy}
            icon={<DownloadCloud aria-hidden className="button__icon" />}
            loading={activeProfile === "local-ai"}
            onClick={() => void installRuntimeProfile("local-ai")}
            variant="ghost"
          >
            {t("system.runtime.installLocalAi")}
          </AsyncButton>
        </div>
      </div>
      <div className="desktop-runtime-settings__list">
        {visibleCandidates.length ? (
          visibleCandidates.map((candidate) => {
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
                {candidate.path ? <code>{candidate.displayPath ?? candidate.path}</code> : null}
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
    </section>
  );
}
