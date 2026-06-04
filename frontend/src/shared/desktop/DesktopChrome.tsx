import { Maximize2, Minus, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";

import { useI18n } from "../i18n";
import { Button } from "../ui/Button";
import {
  closeDesktopWindow,
  desktopRestartErrorMessage,
  getDesktopRuntimeState,
  isDesktopBridgeConnectionError,
  isDesktopRestarting,
  isTauriDesktop,
  minimizeDesktopWindow,
  onDesktopRuntimeProgress,
  repairDesktopRuntime,
  selectDesktopRuntime,
  startDesktopWindowDrag,
  toggleMaximizeDesktopWindow,
  writeDesktopRestartDebugLog,
  type DesktopRuntimeCandidate,
  type DesktopRuntimeCandidateStatus,
  type DesktopRuntimeProgress,
  type DesktopRuntimeRepairAction,
  type DesktopRuntimeState,
} from "./desktopApi";
import { RuntimeProgressPanel } from "./RuntimeProgressPanel";

function DesktopTitleBar() {
  const { t } = useI18n();
  const runWindowAction = useCallback((action: () => Promise<void>) => {
    void action().catch((error) => {
      console.error("Desktop window action failed", error);
    });
  }, []);

  const handleTitleBarMouseDown = useCallback((event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0) {
      return;
    }
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("[data-window-control]")) {
      return;
    }
    void startDesktopWindowDrag().catch((error) => {
      console.error("Desktop window drag failed", error);
    });
  }, []);

  return (
    <header className="desktop-titlebar" data-tauri-drag-region onMouseDown={handleTitleBarMouseDown}>
      <div className="desktop-titlebar__brand" data-tauri-drag-region>
        <img alt="" aria-hidden className="desktop-titlebar__icon" src="/favicon.png" />
        <span className="desktop-titlebar__title">Shinsekai</span>
      </div>
      <div className="desktop-titlebar__controls">
        <button
          aria-label={t("desktop.titlebar.minimize")}
          className="desktop-titlebar__button"
          data-window-control
          onClick={() => runWindowAction(minimizeDesktopWindow)}
          type="button"
        >
          <Minus aria-hidden />
        </button>
        <button
          aria-label={t("desktop.titlebar.maximize")}
          className="desktop-titlebar__button"
          data-window-control
          onClick={() => runWindowAction(toggleMaximizeDesktopWindow)}
          type="button"
        >
          <Maximize2 aria-hidden />
        </button>
        <button
          aria-label={t("desktop.titlebar.close")}
          className="desktop-titlebar__button desktop-titlebar__button--close"
          data-window-control
          onClick={() => runWindowAction(closeDesktopWindow)}
          type="button"
        >
          <X aria-hidden />
        </button>
      </div>
    </header>
  );
}

async function bridgeHealthReady(bridgeUrl: string) {
  if (!bridgeUrl) {
    return false;
  }
  try {
    const response = await fetch(`${bridgeUrl.replace(/\/$/, "")}/api/health`, { cache: "no-store" });
    if (!response.ok) {
      return false;
    }
    const payload = await response.json().catch(() => null);
    return payload?.ok === true;
  } catch (error) {
    if (isDesktopBridgeConnectionError(error)) {
      void writeDesktopRestartDebugLog(
        `DesktopRuntimeGate health fetch bridge error: ${desktopRestartErrorMessage(error)}`,
      );
    }
    return false;
  }
}

function DesktopRuntimeGate({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<DesktopRuntimeState>({
    bridgeUrl: "",
    candidates: [],
    status: "checking",
  });
  const [runtimeProgress, setRuntimeProgress] = useState<DesktopRuntimeProgress | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stopped = false;
    let timer = 0;

    const refresh = async () => {
      try {
        const next = await getDesktopRuntimeState();
        if (stopped) {
          return;
        }
        if (next.status === "ready" && !(await bridgeHealthReady(next.bridgeUrl))) {
          if (!stopped) {
            setRuntime({
              ...next,
              message: t("desktop.runtime.waitingBridge"),
              status: "checking",
            });
            timer = window.setTimeout(refresh, 500);
          }
          return;
        }
        setRuntime(next);
        if (next.status === "checking" || next.status === "updating") {
          timer = window.setTimeout(refresh, 700);
        }
      } catch (error) {
        if (stopped) {
          return;
        }
        if (isDesktopRestarting()) {
          const message = desktopRestartErrorMessage(error);
          void writeDesktopRestartDebugLog(`DesktopRuntimeGate suppressed restart error: ${message}`);
          return;
        }
        if (isDesktopBridgeConnectionError(error)) {
          void writeDesktopRestartDebugLog(
            `DesktopRuntimeGate displayed bridge error: ${desktopRestartErrorMessage(error)}`,
          );
        }
        if (!stopped) {
          setRuntime({
            bridgeUrl: "",
            candidates: [],
            message: desktopRestartErrorMessage(error),
            status: "error",
          });
        }
      }
    };

    void refresh();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    let stopped = false;
    let dispose: (() => void) | null = null;
    void onDesktopRuntimeProgress((progress) => {
      if (!stopped) {
        setRuntimeProgress(progress);
      }
    })
      .then((unlisten) => {
        if (stopped) {
          unlisten();
          return;
        }
        dispose = unlisten;
      })
      .catch((error) => {
        console.error("Desktop runtime progress listener failed", error);
      });
    return () => {
      stopped = true;
      dispose?.();
    };
  }, []);

  const handleStartCandidate = useCallback(async (candidateId: string) => {
    setBusy(true);
    setRuntime((current) => ({ ...current, status: "checking" }));
    try {
      setRuntime(await selectDesktopRuntime(candidateId));
    } catch (error) {
      if (isDesktopBridgeConnectionError(error)) {
        void writeDesktopRestartDebugLog(
          `DesktopRuntimeGate start displayed bridge error: ${desktopRestartErrorMessage(error)}`,
        );
      }
      setRuntime((current) => ({
        ...current,
        message: desktopRestartErrorMessage(error),
        status: "error",
      }));
    } finally {
      setBusy(false);
    }
  }, []);

  const handleRepairCandidate = useCallback(async (candidateId: string, action: DesktopRuntimeRepairAction) => {
    setBusy(true);
    setRuntime((current) => ({ ...current, status: "updating" }));
    try {
      setRuntime(await repairDesktopRuntime(candidateId, action));
    } catch (error) {
      if (isDesktopBridgeConnectionError(error)) {
        void writeDesktopRestartDebugLog(
          `DesktopRuntimeGate repair displayed bridge error: ${desktopRestartErrorMessage(error)}`,
        );
      }
      setRuntime((current) => ({
        ...current,
        message: desktopRestartErrorMessage(error),
        status: "error",
      }));
    } finally {
      setBusy(false);
    }
  }, []);

  if (runtime.status === "ready") {
    return <>{children}</>;
  }

  const detail = runtime.message || t("desktop.runtime.defaultDetail");
  const title =
    runtime.status === "checking"
      ? t("desktop.runtime.checking")
      : runtime.status === "updating"
        ? t("desktop.runtime.updating")
        : t("desktop.runtime.required");
  const candidates = runtime.candidates ?? [];

  return (
    <main className="desktop-runtime">
      <section className="desktop-runtime__panel" aria-live="polite">
        <div className="desktop-runtime__status">
          <span aria-hidden className="desktop-runtime__pulse" />
          <div>
            <p className="desktop-runtime__eyebrow">{t("desktop.runtime.eyebrow")}</p>
            <h1 className="desktop-runtime__title">{title}</h1>
          </div>
        </div>
        <p className="desktop-runtime__message">{detail}</p>
        {runtimeProgress ? <RuntimeProgressPanel progress={runtimeProgress} /> : null}
        {candidates.length ? (
          <div className="desktop-runtime__candidates">
            <h2>{t("desktop.runtime.candidates")}</h2>
            <div className="desktop-runtime__candidate-list">
              {candidates.map((candidate) => (
                <RuntimeCandidateRow
                  busy={busy}
                  candidate={candidate}
                  key={candidate.id}
                  onRepair={handleRepairCandidate}
                  onStart={handleStartCandidate}
                  statusLabel={runtimeCandidateStatusLabel(candidate.status, t)}
                />
              ))}
            </div>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function RuntimeCandidateRow({
  busy,
  candidate,
  onRepair,
  onStart,
  statusLabel,
}: {
  busy: boolean;
  candidate: DesktopRuntimeCandidate;
  onRepair: (candidateId: string, action: DesktopRuntimeRepairAction) => void;
  onStart: (candidateId: string) => void;
  statusLabel: string;
}) {
  const { t } = useI18n();
  const missing = [...candidate.missingPackages, ...candidate.missingImports];
  const canCreateManagedVenv = candidate.repairActions.includes("createManagedVenv");
  const canInstallRuntimeDeps = candidate.repairActions.includes("installRuntimeDeps");
  return (
    <article className="desktop-runtime-candidate" data-status={candidate.status}>
      <div className="desktop-runtime-candidate__header">
        <div>
          <h3>{candidate.label}</h3>
          <p>{candidate.version || candidate.kind}</p>
        </div>
        <span className="desktop-runtime-candidate__status">{statusLabel}</span>
      </div>
      {candidate.pythonVersion ? (
        <p className="desktop-runtime-candidate__message">
          <span>{t("desktop.runtime.candidatePythonVersion")}: </span>
          {candidate.pythonVersion}
        </p>
      ) : null}
      {candidate.path ? (
        <p className="desktop-runtime-candidate__path">
          <span>{t("desktop.runtime.candidatePath")}</span>
          <code>{candidate.displayPath ?? candidate.path}</code>
        </p>
      ) : null}
      {candidate.message ? <p className="desktop-runtime-candidate__message">{candidate.message}</p> : null}
      {missing.length ? (
        <p className="desktop-runtime-candidate__message">
          <span>{t("desktop.runtime.candidateMissing")}: </span>
          {missing.join(", ")}
        </p>
      ) : null}
      {candidate.warnings.length ? (
        <p className="desktop-runtime-candidate__message">
          <span>{t("desktop.runtime.candidateWarnings")}: </span>
          {candidate.warnings.join(" ")}
        </p>
      ) : null}
      {candidate.status === "ready" || canCreateManagedVenv || canInstallRuntimeDeps ? (
        <div className="desktop-runtime-candidate__actions">
          {candidate.status === "ready" ? (
            <Button disabled={busy} onClick={() => onStart(candidate.id)}>
              {t("desktop.runtime.useCandidate")}
            </Button>
          ) : null}
          {canCreateManagedVenv ? (
            <Button disabled={busy} onClick={() => onRepair(candidate.id, "createManagedVenv")} variant="primary">
              {t("desktop.runtime.createVenvButton")}
            </Button>
          ) : null}
          {canInstallRuntimeDeps ? (
            <Button disabled={busy} onClick={() => onRepair(candidate.id, "installRuntimeDeps")} variant="primary">
              {t("desktop.runtime.installDepsButton")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

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

export function DesktopChrome({ children }: { children: ReactNode }) {
  const desktop = useMemo(() => isTauriDesktop(), []);

  if (!desktop) {
    return <>{children}</>;
  }

  return (
    <div className="desktop-frame">
      <DesktopTitleBar />
      <div className="desktop-frame__content">
        <DesktopRuntimeGate>{children}</DesktopRuntimeGate>
      </div>
    </div>
  );
}
