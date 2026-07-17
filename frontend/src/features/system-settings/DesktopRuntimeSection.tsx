import { useCallback, useEffect, useState } from "react";
import { DownloadCloud, Wrench } from "lucide-react";

import {
  getDesktopRuntimeState,
  installDesktopRuntimeProfile,
  isTauriDesktop,
  onDesktopRuntimeProgress,
  repairDesktopRuntime,
  type DesktopRuntimeCandidate,
  type DesktopRuntimeCandidateStatus,
  type DesktopRuntimeProgress,
  type DesktopRuntimeProfile,
  type DesktopRuntimeState,
} from "../../shared/desktop/desktopApi";
import { RuntimeProgressPanel } from "../../shared/desktop/RuntimeProgressPanel";
import { appendRuntimeProgressLog } from "../../shared/desktop/runtimeProgressLog";
import { useI18n } from "../../shared/i18n";
import { AsyncButton } from "../../shared/ui";

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

export function DesktopRuntimeSection() {
  const desktop = isTauriDesktop();
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<DesktopRuntimeState | null>(null);
  const [runtimeProgress, setRuntimeProgress] = useState<DesktopRuntimeProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeRuntimeAction, setActiveRuntimeAction] = useState<DesktopRuntimeProfile | "core" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runRuntimeAction = useCallback(
    async (action: () => Promise<DesktopRuntimeState>, activeAction?: DesktopRuntimeProfile | "core") => {
      setBusy(true);
      setActiveRuntimeAction(activeAction ?? null);
      setError(null);
      try {
        setRuntime(await action());
      } catch (error) {
        setError(error instanceof Error ? error.message : String(error));
      } finally {
        setActiveRuntimeAction(null);
        setBusy(false);
      }
    },
    [],
  );

  const refresh = useCallback(() => runRuntimeAction(getDesktopRuntimeState), [runRuntimeAction]);
  const installRuntimeProfile = useCallback(
    (profile: DesktopRuntimeProfile) => runRuntimeAction(() => installDesktopRuntimeProfile(profile), profile),
    [runRuntimeAction],
  );
  const repairCoreDeps = useCallback(
    (candidateId: string) => runRuntimeAction(() => repairDesktopRuntime(candidateId, "installRuntimeDeps"), "core"),
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
        setRuntimeProgress((current) => appendRuntimeProgressLog(current, progress));
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
  const currentCandidate = visibleCandidates[0] ?? null;

  return (
    <section className="section desktop-runtime-settings page-section-anchor" id="system-runtime">
      <div className="section__header">
        <div>
          <h2 className="section__title">{t("system.runtime.title")}</h2>
          <p className="section__description">{t("system.runtime.description")}</p>
        </div>
        <div className="page__actions desktop-runtime-settings__primary-actions">
          <AsyncButton
            disabled={busy || !currentCandidate}
            icon={<Wrench aria-hidden className="button__icon" />}
            loading={activeRuntimeAction === "core"}
            onClick={() => {
              if (currentCandidate) {
                void repairCoreDeps(currentCandidate.id);
              }
            }}
            variant="ghost"
          >
            {t("system.runtime.repairCoreDeps")}
          </AsyncButton>
          <AsyncButton
            disabled={busy}
            icon={<DownloadCloud aria-hidden className="button__icon" />}
            loading={activeRuntimeAction === "local-ai"}
            onClick={() => void installRuntimeProfile("local-ai")}
            variant="ghost"
          >
            {t("system.runtime.installLocalAi")}
          </AsyncButton>
        </div>
      </div>
      {runtime?.message || error ? (
        <p className="desktop-runtime-settings__message">{error ?? runtime?.message}</p>
      ) : null}
      {runtimeProgress ? <RuntimeProgressPanel progress={runtimeProgress} /> : null}
      <div className="desktop-runtime-settings__list">
        {visibleCandidates.length ? (
          visibleCandidates.map((candidate) => {
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
