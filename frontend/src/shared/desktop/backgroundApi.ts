import type { FrontendLanguage } from "../i18n/messages";

export interface BackgroundPreferences {
  closeToTray: boolean;
  rememberCloseAction: boolean;
  minimizeToTray: boolean;
  bedtimeEnabled: boolean;
  bedtimeTime: string;
  language: FrontendLanguage;
}

export interface BackgroundStatus {
  preferences: BackgroundPreferences;
  trayAvailable: boolean;
}

export async function getBackgroundPreferences() {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<BackgroundStatus>("desktop_background_get");
}

export async function saveBackgroundPreferences(preferences: BackgroundPreferences) {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<BackgroundStatus>("desktop_background_save", { preferences });
}

export async function testBedtimeNotification(language: FrontendLanguage) {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<void>("desktop_background_test", { language });
}
