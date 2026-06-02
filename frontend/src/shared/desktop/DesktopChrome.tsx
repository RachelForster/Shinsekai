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
  startDesktopWindowDrag,
  toggleMaximizeDesktopWindow,
  updateDesktopRuntime,
  writeDesktopRestartDebugLog,
  type DesktopRuntimeState,
} from "./desktopApi";

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
      void writeDesktopRestartDebugLog(`DesktopRuntimeGate health fetch bridge error: ${desktopRestartErrorMessage(error)}`);
    }
    return false;
  }
}

function DesktopRuntimeGate({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<DesktopRuntimeState>({
    bridgeUrl: "",
    status: "checking",
  });
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

  const handleUpdate = useCallback(async () => {
    setBusy(true);
    setRuntime((current) => ({ ...current, status: "updating" }));
    try {
      setRuntime(await updateDesktopRuntime());
    } catch (error) {
      if (isDesktopBridgeConnectionError(error)) {
        void writeDesktopRestartDebugLog(
          `DesktopRuntimeGate update displayed bridge error: ${desktopRestartErrorMessage(error)}`,
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

  const canUpdate = runtime.status === "missing" || runtime.status === "error";
  const detail = runtime.message || t("desktop.runtime.defaultDetail");
  const title =
    runtime.status === "checking"
      ? t("desktop.runtime.checking")
      : runtime.status === "updating"
        ? t("desktop.runtime.updating")
        : t("desktop.runtime.required");

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
        <div className="desktop-runtime__actions">
          {canUpdate ? (
            <Button disabled={busy} loading={busy} onClick={handleUpdate} variant="primary">
              {t("desktop.runtime.updateButton")}
            </Button>
          ) : null}
        </div>
      </section>
    </main>
  );
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
