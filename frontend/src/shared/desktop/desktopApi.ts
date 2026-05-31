export type DesktopRuntimeStatus = "checking" | "missing" | "updating" | "ready" | "error";

export interface DesktopRuntimeState {
  status: DesktopRuntimeStatus;
  message?: string | null;
  bridgeUrl: string;
}

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

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
