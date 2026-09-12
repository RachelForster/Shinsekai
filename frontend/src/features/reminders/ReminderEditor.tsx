import { useState } from "react";
import type { Character } from "../../entities/config/types";
import type { ScheduledReminder } from "../../entities/reminder/types";
import type { MessageKey } from "../../shared/i18n";

function localDateTime(value: string) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function ReminderEditor({
  reminder,
  characters,
  t,
  onSave,
  onCancel,
}: {
  reminder: ScheduledReminder;
  characters: Character[];
  t: (key: MessageKey) => string;
  onSave: (changes: Record<string, string>) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState({
    title: reminder.title,
    message: reminder.message,
    character_name: reminder.character_name,
    recurrence: reminder.recurrence,
    remind_at: localDateTime(reminder.due_at),
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <form
      className="reminder-editor"
      aria-label={t("reminder.edit")}
      onSubmit={(event) => {
        event.preventDefault();
        if (busy) return;
        const { remind_at, ...changes } = draft;
        if (remind_at !== localDateTime(reminder.due_at) && new Date(remind_at).getTime() <= Date.now()) {
          setError(t("reminder.futureTime"));
          return;
        }
        setBusy(true);
        setError("");
        void onSave({ ...changes, ...(remind_at !== localDateTime(reminder.due_at) ? { remind_at } : {}) })
          .catch((reason: unknown) => {
            setError(String(reason));
          })
          .finally(() => setBusy(false));
      }}
    >
      <h1>{t("reminder.edit")}</h1>
      <fieldset disabled={busy}>
        <label>
          {t("reminder.fieldTitle")}
          <input
            required
            maxLength={120}
            value={draft.title}
            onChange={(event) => setDraft({ ...draft, title: event.target.value })}
          />
        </label>
        <label>
          {t("reminder.character")}
          <select
            value={draft.character_name}
            onChange={(event) => setDraft({ ...draft, character_name: event.target.value })}
          >
            <option value="*">{t("reminder.random")}</option>
            {!characters.some((item) => item.name === draft.character_name) && draft.character_name !== "*" && (
              <option value={draft.character_name}>{draft.character_name}</option>
            )}
            {characters.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <p>{t("reminder.randomHint")}</p>
        <label>
          {t("reminder.fieldMessage")}
          <textarea
            required
            maxLength={2000}
            rows={3}
            value={draft.message}
            onChange={(event) => setDraft({ ...draft, message: event.target.value })}
          />
        </label>
        <label>
          {t("reminder.fieldTime")}
          <input
            type="datetime-local"
            required
            value={draft.remind_at}
            onChange={(event) => setDraft({ ...draft, remind_at: event.target.value })}
          />
        </label>
        <label>
          {t("reminder.recurrence")}
          <select
            value={draft.recurrence}
            onChange={(event) =>
              setDraft({ ...draft, recurrence: event.target.value as ScheduledReminder["recurrence"] })
            }
          >
            {(["once", "daily", "weekly"] as const).map((value) => (
              <option key={value} value={value}>
                {t(`reminder.${value}`)}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
      {error && <p role="alert">{error}</p>}
      <footer>
        <button type="button" disabled={busy} onClick={onCancel}>
          {t("common.cancel")}
        </button>
        <button type="submit" disabled={busy}>
          {t("common.save")}
        </button>
      </footer>
    </form>
  );
}
