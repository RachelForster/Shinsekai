export interface ReminderNotice {
  id: string;
  character_name: string;
  title: string;
  message: string;
  due_at: string;
  audio_path?: string | null;
  audio_volume?: number;
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
