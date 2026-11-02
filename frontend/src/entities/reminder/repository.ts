import { requestReminders } from "../../shared/desktop/remindersApi";
import type { ReminderList, ReminderNotice } from "./types";

export const getReminderInbox = () => requestReminders<ReminderNotice[]>("inbox");
export const listReminders = () => requestReminders<ReminderList>("list");
export const cancelReminder = (id: string) => requestReminders("cancel", { id });
export const deleteReminder = (id: string) => requestReminders("delete", { id });
export const updateReminder = (id: string, changes: Record<string, string>) =>
  requestReminders("update", { id, changes });
export const dismissReminder = (notice: ReminderNotice) =>
  requestReminders("dismiss", { id: notice.id, dueAt: notice.due_at });
