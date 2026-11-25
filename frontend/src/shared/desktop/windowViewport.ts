import { isTauriDesktop, type DesktopEventUnlisten } from "./desktopApi";

export async function isDesktopWindowExpanded(): Promise<boolean> {
  if (!isTauriDesktop()) {
    return false;
  }
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const win = getCurrentWindow();
    const [maximized, fullscreen] = await Promise.all([win.isMaximized(), win.isFullscreen()]);
    return Boolean(maximized || fullscreen);
  } catch {
    return false;
  }
}

export async function subscribeDesktopWindowResize(listener: () => void): Promise<DesktopEventUnlisten> {
  if (!isTauriDesktop()) {
    return () => undefined;
  }
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    return await getCurrentWindow().onResized(() => listener());
  } catch {
    return () => undefined;
  }
}
