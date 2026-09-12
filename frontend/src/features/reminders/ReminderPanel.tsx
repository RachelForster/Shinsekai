import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { Bell, Check, ChevronRight, Home, SlidersHorizontal, X } from "lucide-react";

import { listCharacters } from "../../entities/character/repository";
import { getAppConfig } from "../../entities/config/repository";
import type { Character } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { cancelReminder, dismissReminder, getReminderInbox, listReminders } from "../../entities/reminder/repository";
import type { ReminderNotice, ScheduledReminder } from "../../entities/reminder/types";
import { onRemindersChanged, reminderWindow } from "../../shared/desktop/remindersApi";
import { applyThemeColor } from "../../shared/theme/appTheme";
import "./ReminderPanel.css";

import { reminderPanelCopy as copy } from "../../shared/i18n/reminderPanelCopy";

function initialCrop() {
  try {
    const value = Number(localStorage.getItem("shinsekai.reminder.portraitCrop"));
    return value >= 0.25 && value <= 0.75 ? value : 0.5;
  } catch {
    return 0.5;
  }
}

export function ReminderPanel() {
  const [inbox, setInbox] = useState<ReminderNotice[]>([]);
  const [schedules, setSchedules] = useState<ScheduledReminder[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [language, setLanguage] = useState<keyof typeof copy>("zh_CN");
  const [selected, setSelected] = useState<ReminderNotice | null>(null);
  const [tab, setTab] = useState<"upcoming" | "inbox">("upcoming");
  const [crop, setCrop] = useState(initialCrop);
  const [customize, setCustomize] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const text = copy[language];
  const latestNotice = useRef("");
  const refreshVersion = useRef(0);

  const refresh = useCallback(async () => {
    const version = ++refreshVersion.current;
    // Load the native inbox even if the backend is temporarily restarting.
    const results = await Promise.allSettled([getReminderInbox(), listReminders(), listCharacters(), getAppConfig()]);
    if (version !== refreshVersion.current) return;
    const [notices, pending, people, config] = results;
    if (notices.status === "fulfilled") {
      setInbox(notices.value);
      const newest = notices.value[0];
      const key = newest ? `${newest.id}:${newest.due_at}` : "";
      const isNew = !!key && latestNotice.current !== key;
      latestNotice.current = key;
      if (isNew) setTab("inbox");
      setSelected((current) => {
        if (isNew) return newest;
        if (!current) return null;
        return (
          notices.value.find((item) => item.id === current.id && item.due_at === current.due_at) ??
          (pending.status === "fulfilled"
            ? (pending.value.reminders.find((item) => item.id === current.id && item.status === "active") ?? null)
            : current)
        );
      });
    }
    if (pending.status === "fulfilled")
      setSchedules(pending.value.reminders.filter((item) => item.status === "active"));
    if (people.status === "fulfilled") setCharacters(people.value);
    if (config.status === "fulfilled") {
      applyThemeColor(config.value.system_config.theme_color);
      const lang = config.value.system_config.ui_language;
      setLanguage(lang === "en" || lang === "ja" ? lang : "zh_CN");
    }
    const failed = results.find((result) => result.status === "rejected");
    setError(failed?.status === "rejected" ? String(failed.reason) : "");
    setLoading(false);
  }, []);

  useEffect(() => {
    document.documentElement.classList.add("reminder-surface");
    let stopped = false;
    let unlisten: (() => void) | undefined;
    const syncScheme = () => {
      try {
        const scheme = localStorage.getItem("shinsekai-color-scheme");
        if (scheme === "light" || scheme === "dark") document.documentElement.dataset.colorScheme = scheme;
      } catch {
        /* Use the system color scheme when storage is unavailable. */
      }
    };
    syncScheme();
    window.addEventListener("storage", syncScheme);
    void onRemindersChanged(() => {
      syncScheme();
      void refresh();
    })
      .then((cleanup) => {
        if (stopped) cleanup();
        else unlisten = cleanup;
      })
      .catch((reason: unknown) => setError(String(reason)));
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") void reminderWindow("hide");
    };
    window.addEventListener("keydown", onKey);
    return () => {
      ++refreshVersion.current;
      stopped = true;
      unlisten?.();
      window.clearInterval(timer);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("storage", syncScheme);
      document.documentElement.classList.remove("reminder-surface");
    };
  }, [refresh]);

  const run = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      await refresh();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };
  const current = selected ?? inbox[0] ?? schedules[0];
  const character = current ? characters.find((item) => item.name === current.character_name) : characters[0];
  const portrait = character?.sprites[0]?.path;
  const received = !!current && inbox.some((item) => item.id === current.id && item.due_at === current.due_at);
  const rows = tab === "inbox" ? inbox : schedules;
  const formatTime = (value: string) =>
    new Date(value).toLocaleString(language === "zh_CN" ? "zh-CN" : language, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <main className="reminder-panel" aria-label={text.title}>
      <header className="reminder-panel__header">
        <span>
          <Bell size={15} /> Shinsekai <span className="reminder-panel__muted">/ {text.title}</span>
        </span>
        <button aria-label={text.close} onClick={() => void run(() => reminderWindow("hide"))}>
          <X size={17} />
        </button>
      </header>
      <section className="reminder-panel__hero" aria-live="polite">
        <div className="reminder-panel__portrait" style={{ "--portrait-crop": crop } as CSSProperties}>
          <span aria-hidden>{(character?.name ?? current?.character_name ?? "S").slice(0, 1)}</span>
          {portrait && (
            <img
              key={portrait}
              src={fileUrl(portrait)}
              alt={character?.name ?? ""}
              onError={(event) => {
                event.currentTarget.style.display = "none";
              }}
            />
          )}
          <div className="reminder-panel__portrait-label">
            {character?.name ?? current?.character_name ?? "Shinsekai"}
          </div>
        </div>
        <div className="reminder-panel__message">
          <span className="reminder-panel__eyebrow">
            {current ? formatTime(current.due_at) : "SHINSEKAI · WITH YOU"}
          </span>
          <h1>{current?.title ?? text.hello}</h1>
          <p>{current?.message ?? text.hint}</p>
          {received && current && (
            <button
              className="reminder-panel__ack"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await dismissReminder(current);
                  setSelected(null);
                })
              }
            >
              <Check size={14} />
              {text.done}
            </button>
          )}
        </div>
      </section>
      <nav className="reminder-panel__tabs" aria-label={text.title}>
        {(["upcoming", "inbox"] as const).map((value) => (
          <button key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>
            {text[value]} <small>{value === "upcoming" ? schedules.length : inbox.length}</small>
          </button>
        ))}
      </nav>
      <div className="reminder-panel__list">
        {loading ? (
          <p className="reminder-panel__empty">{text.load}</p>
        ) : rows.length === 0 ? (
          <p className="reminder-panel__empty">{tab === "upcoming" ? text.empty : text.inbox + " · 0"}</p>
        ) : (
          rows.map((item) => (
            <div className="reminder-panel__row" key={`${item.id}:${item.due_at}`}>
              <button className="reminder-panel__row-main" onClick={() => setSelected(item)}>
                <span>
                  <strong>{item.title}</strong>
                  <small>
                    {item.character_name} · {formatTime(item.due_at)}
                    {"recurrence" in item ? ` · ${text[(item as ScheduledReminder).recurrence]}` : ""}
                  </small>
                </span>
                <ChevronRight size={14} />
              </button>
              <button
                aria-label={`${tab === "upcoming" ? text.cancel : text.done}: ${item.title}`}
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    if (tab === "upcoming") await cancelReminder(item.id);
                    else await dismissReminder(item);
                    setSelected(null);
                  })
                }
              >
                <X size={14} />
              </button>
            </div>
          ))
        )}
      </div>
      {error && (
        <div role="alert" className="reminder-panel__error">
          <span>{error}</span>
          <button onClick={() => void refresh()}>{text.retry}</button>
        </div>
      )}
      {customize && (
        <label className="reminder-panel__crop">
          {text.top} {Math.round(crop * 100)}%
          <input
            aria-label={text.crop}
            type="range"
            min="0.25"
            max="0.75"
            step="0.05"
            value={crop}
            onChange={(event) => {
              const value = Number(event.target.value);
              setCrop(value);
              try {
                localStorage.setItem("shinsekai.reminder.portraitCrop", String(value));
              } catch {
                /* Keep the adjustment for this session. */
              }
            }}
          />
        </label>
      )}
      <footer className="reminder-panel__footer">
        <button onClick={() => void run(() => reminderWindow("main"))}>
          <Home size={14} />
          {text.main}
        </button>
        <span>{text.running}</span>
        <button aria-label={text.crop} aria-expanded={customize} onClick={() => setCustomize(!customize)}>
          <SlidersHorizontal size={15} />
        </button>
      </footer>
    </main>
  );
}
