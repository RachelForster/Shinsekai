import { Maximize2, Minus, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";

import { Button } from "../ui/Button";
import {
  closeDesktopWindow,
  getDesktopRuntimeState,
  isTauriDesktop,
  minimizeDesktopWindow,
  startDesktopWindowDrag,
  toggleMaximizeDesktopWindow,
  updateDesktopRuntime,
  type DesktopRuntimeState,
} from "./desktopApi";

function DesktopTitleBar() {
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
          aria-label="最小化"
          className="desktop-titlebar__button"
          data-window-control
          onClick={() => runWindowAction(minimizeDesktopWindow)}
          type="button"
        >
          <Minus aria-hidden />
        </button>
        <button
          aria-label="最大化"
          className="desktop-titlebar__button"
          data-window-control
          onClick={() => runWindowAction(toggleMaximizeDesktopWindow)}
          type="button"
        >
          <Maximize2 aria-hidden />
        </button>
        <button
          aria-label="关闭"
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

function DesktopRuntimeGate({ children }: { children: ReactNode }) {
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
        setRuntime(next);
        if (next.status === "checking" || next.status === "updating") {
          timer = window.setTimeout(refresh, 700);
        }
      } catch (error) {
        if (!stopped) {
          setRuntime({
            bridgeUrl: "",
            message: error instanceof Error ? error.message : String(error),
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
      setRuntime((current) => ({
        ...current,
        message: error instanceof Error ? error.message : String(error),
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
  const detail = runtime.message || "正在检查 Shinsekai 运行环境。";
  const title =
    runtime.status === "checking"
      ? "正在检查运行环境"
      : runtime.status === "updating"
        ? "正在更新运行环境"
        : "需要更新运行环境";

  return (
    <main className="desktop-runtime">
      <section className="desktop-runtime__panel" aria-live="polite">
        <div className="desktop-runtime__status">
          <span aria-hidden className="desktop-runtime__pulse" />
          <div>
            <p className="desktop-runtime__eyebrow">运行环境</p>
            <h1 className="desktop-runtime__title">{title}</h1>
          </div>
        </div>
        <p className="desktop-runtime__message">{detail}</p>
        <div className="desktop-runtime__actions">
          {canUpdate ? (
            <Button disabled={busy} loading={busy} onClick={handleUpdate} variant="primary">
              是，更新
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
