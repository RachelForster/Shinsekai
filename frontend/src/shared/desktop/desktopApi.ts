export type DesktopRuntimeStatus = "checking" | "missing" | "updating" | "ready" | "error";

export interface DesktopRuntimeState {
  status: DesktopRuntimeStatus;
  message?: string | null;
  bridgeUrl: string;
}

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
    __SHINSEKAI_RESTARTING__?: boolean;
    __SHINSEKAI_BRIDGE_RESTARTING__?: boolean;
  }
}

const bridgeRestartFinishedEvent = "shinsekai:bridge-restart-finished";

export function isTauriDesktop() {
  if (typeof window === "undefined") {
    return false;
  }
  return (
    Boolean(window.__TAURI_INTERNALS__) ||
    window.location.protocol === "tauri:" ||
    window.location.hostname === "tauri.localhost"
  );
}

async function invokeDesktop<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(command, args);
}

export function getDesktopRuntimeState() {
  return invokeDesktop<DesktopRuntimeState>("desktop_runtime_state");
}

export function updateDesktopRuntime() {
  return invokeDesktop<DesktopRuntimeState>("desktop_runtime_update");
}

export async function restartDesktopBridge() {
  markDesktopBridgeRestarting();
  console.info("[restart-debug] frontend restartDesktopBridge invoked");
  await writeDesktopRestartDebugLog("restartDesktopBridge invoked");
  try {
    const state = await invokeDesktop<DesktopRuntimeState>("desktop_bridge_restart");
    await writeDesktopRestartDebugLog(`desktop_bridge_restart returned status=${state.status}`);
    return state;
  } catch (error) {
    await writeDesktopRestartDebugLog(`desktop_bridge_restart rejected: ${desktopRestartErrorMessage(error)}`);
    throw error;
  } finally {
    clearDesktopBridgeRestarting();
  }
}

export async function restartDesktopApp() {
  markDesktopRestarting();
  console.info("[restart-debug] frontend restartDesktopApp invoked");
  await writeDesktopRestartDebugLog("restartDesktopApp invoked");
  try {
    await invokeDesktop<void>("desktop_app_restart");
    await writeDesktopRestartDebugLog("desktop_app_restart invoke returned; waiting for old window to exit");
  } catch (error) {
    const message = desktopRestartErrorMessage(error);
    await writeDesktopRestartDebugLog(`desktop_app_restart invoke rejected: ${message}`);
    if (!isExpectedDesktopRestartDisconnect(error)) {
      clearDesktopRestarting();
      throw error;
    }
  }
  return waitForDesktopRestartExit();
}

export async function writeDesktopRestartDebugLog(message: string) {
  if (!isTauriDesktop()) {
    return;
  }
  try {
    await invokeDesktop<void>("desktop_restart_debug_log", { message });
  } catch (error) {
    console.error("[restart-debug] frontend log command failed", error);
  }
}

export function markDesktopRestarting() {
  if (typeof window !== "undefined") {
    window.__SHINSEKAI_RESTARTING__ = true;
  }
}

export function isDesktopRestarting() {
  return typeof window !== "undefined" && window.__SHINSEKAI_RESTARTING__ === true;
}

export function clearDesktopRestarting() {
  if (typeof window !== "undefined") {
    window.__SHINSEKAI_RESTARTING__ = false;
  }
}

export function markDesktopBridgeRestarting() {
  if (typeof window !== "undefined") {
    window.__SHINSEKAI_BRIDGE_RESTARTING__ = true;
  }
}

export function isDesktopBridgeRestarting() {
  return typeof window !== "undefined" && window.__SHINSEKAI_BRIDGE_RESTARTING__ === true;
}

export function clearDesktopBridgeRestarting() {
  if (typeof window !== "undefined") {
    window.__SHINSEKAI_BRIDGE_RESTARTING__ = false;
    window.dispatchEvent(new Event(bridgeRestartFinishedEvent));
  }
}

export function waitForDesktopBridgeRestart(timeoutMs = 15000) {
  if (!isDesktopBridgeRestarting() || typeof window === "undefined") {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    const finish = () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener(bridgeRestartFinishedEvent, finish);
      resolve();
    };
    const timeoutId = window.setTimeout(finish, timeoutMs);
    window.addEventListener(bridgeRestartFinishedEvent, finish, { once: true });
  });
}

export function desktopRestartErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

export function isExpectedDesktopRestartDisconnect(error: unknown) {
  return isDesktopBridgeConnectionError(error) || isDesktopIpcDisconnect(error);
}

export function isDesktopBridgeConnectionError(error: unknown) {
  const message = desktopRestartErrorMessage(error).toLowerCase();
  return (
    message.includes("127.0.0.1") ||
    message.includes("localhost") ||
    message.includes("connection refused") ||
    message.includes("could not connect") ||
    message.includes("connection reset") ||
    message.includes("connection closed") ||
    message.includes("failed to fetch") ||
    message.includes("network")
  );
}

function isDesktopIpcDisconnect(error: unknown) {
  const message = desktopRestartErrorMessage(error).toLowerCase();
  return (
    message.includes("ipc") ||
    message.includes("channel")
  );
}

function waitForDesktopRestartExit(): Promise<never> {
  return new Promise(() => {});
}

export function minimizeDesktopWindow() {
  return invokeDesktop<void>("desktop_window_minimize");
}

export function toggleMaximizeDesktopWindow() {
  return invokeDesktop<void>("desktop_window_toggle_maximize");
}

export function startDesktopWindowDrag() {
  return invokeDesktop<void>("desktop_window_start_drag");
}

export function closeDesktopWindow() {
  return invokeDesktop<void>("desktop_window_close");
}

export function openDesktopExternalUrl(url: string) {
  return invokeDesktop<void>("desktop_open_external_url", { url });
}
