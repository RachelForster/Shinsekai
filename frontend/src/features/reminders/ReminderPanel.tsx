import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import {
  Bell,
  Pencil,
  Check,
  ChevronLeft,
  ChevronRight,
  Home,
  SlidersHorizontal,
  Volume2,
  VolumeX,
  Play,
  X,
} from "lucide-react";

import { listCharacters } from "../../entities/character/repository";
import { getAppConfig } from "../../entities/config/repository";
import type { Character } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import {
  deleteReminder,
  updateReminder,
  dismissReminder,
  getReminderInbox,
  listReminders,
} from "../../entities/reminder/repository";
import type { ReminderNotice, ScheduledReminder } from "../../entities/reminder/types";
import {
  getReminderView,
  onReminderViewChanged,
  onRemindersChanged,
  onRemindersUpdated,
  reminderWindow,
} from "../../shared/desktop/remindersApi";
import { translateMessage, type FrontendLanguage, type MessageKey } from "../../shared/i18n";
import { applyThemeColor } from "../../shared/theme/appTheme";
import { ReminderEditor } from "./ReminderEditor";
import { CompactReminderCard } from "./CompactReminderCard";
import { useReminderAudio } from "./useReminderAudio";
import "./ReminderPanel.css";

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
  const [language, setLanguage] = useState<FrontendLanguage>("zh_CN");
  const [selected, setSelected] = useState<ReminderNotice | null>(null);
  const [tab, setTab] = useState<"upcoming" | "inbox">("upcoming");
  const [crop, setCrop] = useState(initialCrop);
  const [customize, setCustomize] = useState(false);
  const [management, setManagement] = useState(false);
  const [editing, setEditing] = useState<ScheduledReminder | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const t = (key: MessageKey) => translateMessage(language, key);
  const latestNotice = useRef("");
  const refreshVersion = useRef(0);
  const voice = useReminderAudio(inbox);

  useEffect(() => {
    const speaking = inbox.find((notice) => `${notice.id}:${notice.due_at}` === voice.playing);
    if (speaking) setSelected(speaking);
  }, [voice.playing]);

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
    if (pending.status === "fulfilled") setSchedules(pending.value.reminders);
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
    let unlistenUpdates: (() => void) | undefined;
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
      setManagement(false);
      syncScheme();
      void refresh();
    })
      .then((cleanup) => {
        if (stopped) cleanup();
        else unlisten = cleanup;
      })
      .catch((reason: unknown) => setError(String(reason)));
    void onRemindersUpdated(() => void refresh())
      .then((cleanup) => {
        if (stopped) cleanup();
        else unlistenUpdates = cleanup;
      })
      .catch((reason: unknown) => setError(String(reason)));
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        voice.stop();
        void reminderWindow("hide");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      ++refreshVersion.current;
      stopped = true;
      unlisten?.();
      unlistenUpdates?.();
      window.clearInterval(timer);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("storage", syncScheme);
      document.documentElement.classList.remove("reminder-surface");
    };
  }, [refresh]);

  useEffect(() => {
    let stopped = false;
    let revision = 0;
    let dispose: (() => void) | undefined;
    const applyView = (expanded: boolean) => {
      setManagement(expanded);
      if (expanded) setTab("upcoming");
      void refresh();
    };
    void (async () => {
      dispose = await onReminderViewChanged((expanded) => {
        ++revision;
        if (!stopped) applyView(expanded);
      });
      if (stopped) {
        dispose();
        return;
      }
      const before = revision;
      const expanded = await getReminderView();
      if (!stopped && before === revision) applyView(expanded);
    })().catch((reason: unknown) => {
      if (!stopped) setError(String(reason));
    });
    return () => {
      stopped = true;
      dispose?.();
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
  const activeNotice = inbox.find((item) => item.id === selected?.id && item.due_at === selected?.due_at) ?? inbox[0];
  const current = management ? (selected ?? inbox[0] ?? schedules[0]) : activeNotice;
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

  const changeView = (expanded: boolean) =>
    void run(async () => {
      await reminderWindow(expanded ? "manage" : "compact");
      setManagement(expanded);
    });
  const voiceControls = (
    <>
      {current?.audio_path && (
        <button
          aria-label={t("reminder.playVoice")}
          title={t("reminder.playVoice")}
          disabled={voice.muted}
          onClick={() => voice.replay(current)}
        >
          <Play size={15} />
        </button>
      )}
      <button
        aria-label={voice.muted ? t("reminder.unmuteVoice") : t("reminder.muteVoice")}
        title={voice.muted ? t("reminder.unmuteVoice") : t("reminder.muteVoice")}
        onClick={voice.toggleMute}
      >
        {voice.muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
      </button>
    </>
  );
  const portraitElement = (
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
    </div>
  );

  if (management && editing) {
    return (
      <main className="reminder-panel">
        <ReminderEditor
          key={editing.id}
          reminder={editing}
          characters={characters}
          t={t}
          onCancel={() => setEditing(null)}
          onSave={async (changes) => {
            await updateReminder(editing.id, changes);
            setEditing(null);
            await refresh();
          }}
        />
      </main>
    );
  }

  if (!management) {
    const index = activeNotice ? inbox.indexOf(activeNotice) : 0;
    return (
      <CompactReminderCard
        portrait={portraitElement}
        name={character?.name ?? current?.character_name ?? "Shinsekai"}
        message={current?.message ?? (loading ? t("reminder.load") : t("reminder.hello"))}
        time={
          current
            ? new Date(current.due_at).toLocaleTimeString(language === "zh_CN" ? "zh-CN" : language, {
                hour: "2-digit",
                minute: "2-digit",
              })
            : ""
        }
        index={index}
        count={inbox.length}
        busy={busy}
        error={error}
        voiceControls={voiceControls}
        t={t}
        onClose={() => {
          voice.stop();
          void run(() => reminderWindow("hide"));
        }}
        onDismiss={() =>
          void run(async () => {
            if (!activeNotice) return;
            voice.stop();
            await dismissReminder(activeNotice);
            setSelected(null);
            if (inbox.length === 1) await reminderWindow("hide");
          })
        }
        onManage={() => changeView(true)}
        onPrevious={() => setSelected(inbox[(index - 1 + inbox.length) % inbox.length])}
        onNext={() => setSelected(inbox[(index + 1) % inbox.length])}
        onRetry={() => void refresh()}
      />
    );
  }

  return (
    <main className="reminder-panel" aria-label={t("reminder.title")}>
      <header className="reminder-panel__header">
        <span>
          <button
            aria-label={t("reminder.back")}
            title={t("reminder.back")}
            disabled={busy}
            onClick={() => changeView(false)}
          >
            <ChevronLeft size={15} />
          </button>
          <Bell size={15} /> Shinsekai <span className="reminder-panel__muted">/ {t("reminder.title")}</span>
        </span>
        {voiceControls}
        <button
          aria-label={t("reminder.close")}
          onClick={() => {
            voice.stop();
            void run(() => reminderWindow("hide"));
          }}
        >
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
          <h1>{current?.title ?? t("reminder.hello")}</h1>
          <p>{current?.message ?? t("reminder.hint")}</p>
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
              {t("reminder.done")}
            </button>
          )}
        </div>
      </section>
      <nav className="reminder-panel__tabs" aria-label={t("reminder.title")}>
        {(["upcoming", "inbox"] as const).map((value) => (
          <button key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>
            {t(`reminder.${value}`)} <small>{value === "upcoming" ? schedules.length : inbox.length}</small>
          </button>
        ))}
      </nav>
      <div className="reminder-panel__list">
        {loading ? (
          <p className="reminder-panel__empty">{t("reminder.load")}</p>
        ) : rows.length === 0 ? (
          <p className="reminder-panel__empty">
            {tab === "upcoming" ? t("reminder.empty") : t("reminder.inbox") + " · 0"}
          </p>
        ) : (
          rows.map((item) => (
            <div className="reminder-panel__row" key={`${item.id}:${item.due_at}`}>
              <button className="reminder-panel__row-main" onClick={() => setSelected(item)}>
                <span>
                  <strong>{item.title}</strong>
                  <small>
                    {item.character_name === "*" ? t("reminder.random") : item.character_name} ·{" "}
                    {formatTime(item.due_at)}
                    {"recurrence" in item
                      ? ` · ${t(`reminder.${(item as ScheduledReminder).recurrence}`)} · ${t(`reminder.status.${(item as ScheduledReminder).status}`)}`
                      : ""}
                  </small>
                </span>
                <ChevronRight size={14} />
              </button>
              {tab === "upcoming" && "status" in item && item.status === "active" && (
                <button
                  aria-label={`${t("reminder.edit")}: ${item.title}`}
                  disabled={busy}
                  onClick={() => setEditing(item as ScheduledReminder)}
                >
                  <Pencil size={14} />
                </button>
              )}
              <button
                aria-label={`${tab === "upcoming" ? t("reminder.delete") : t("reminder.done")}: ${item.title}`}
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    if (tab === "upcoming") await deleteReminder(item.id);
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
          <button onClick={() => void refresh()}>{t("reminder.retry")}</button>
        </div>
      )}
      {customize && (
        <label className="reminder-panel__crop">
          {t("reminder.top")} {Math.round(crop * 100)}%
          <input
            aria-label={t("reminder.crop")}
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
          {t("reminder.main")}
        </button>
        <span>{t("reminder.running")}</span>
        <button aria-label={t("reminder.crop")} aria-expanded={customize} onClick={() => setCustomize(!customize)}>
          <SlidersHorizontal size={15} />
        </button>
      </footer>
    </main>
  );
}
