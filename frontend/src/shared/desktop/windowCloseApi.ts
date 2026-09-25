export interface CloseRequestStatus {
  requested: boolean;
  trayAvailable: boolean;
}

export type CloseAction = "exit" | "tray" | "cancel";
export const closePreferenceChangedEvent = "shinsekai:close-preference-changed";

export async function getCloseRequestStatus() {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<CloseRequestStatus>("desktop_window_close_status");
}

export async function onCloseRequested(callback: (status: CloseRequestStatus) => void) {
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return getCurrentWindow().listen<CloseRequestStatus>("shinsekai:close-requested", (event) => callback(event.payload));
}

export async function resolveCloseRequest(action: CloseAction, remember: boolean) {
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke<void>("desktop_window_resolve_close", { action, remember });
  if (remember && action !== "cancel") window.dispatchEvent(new Event(closePreferenceChangedEvent));
}
