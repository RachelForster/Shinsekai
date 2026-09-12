import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface ReminderNotice {
  id: string;
  character_name: string;
  title: string;
  message: string;
  due_at: string;
}

export interface ScheduledReminder extends ReminderNotice {
  recurrence: "once" | "daily" | "weekly";
  status: "active" | "completed" | "cancelled" | "missed";
}

export interface ReminderList {
  reminders: ScheduledReminder[];
  desktop_connected: boolean;
  now: string;
}

export const getReminderInbox = () => invoke<ReminderNotice[]>("desktop_reminders_inbox");
export const onRemindersChanged = (callback: () => void) => listen("shinsekai:reminders-changed", callback);
export const listReminders = () => invoke<ReminderList>("desktop_reminders_list");
export const cancelReminder = (id: string) => invoke("desktop_reminders_cancel", { id });
export const dismissReminder = (notice: ReminderNotice) =>
  invoke("desktop_reminders_dismiss", { id: notice.id, dueAt: notice.due_at });
export const reminderWindow = (action: "open" | "hide" | "main") =>
  invoke<void>("desktop_reminders_window", { action });
