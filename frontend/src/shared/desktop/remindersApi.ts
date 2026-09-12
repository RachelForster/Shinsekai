import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export function requestReminders<T = unknown>(
  action: "inbox" | "list" | "cancel" | "dismiss",
  args?: { id: string; dueAt?: string },
) {
  return invoke<T>(`desktop_reminders_${action}`, args);
}
export const onRemindersChanged = (callback: () => void) => listen("shinsekai:reminders-changed", callback);
export const reminderWindow = (action: "open" | "hide" | "main" | "manage" | "compact") =>
  invoke<void>("desktop_reminders_window", { action });
