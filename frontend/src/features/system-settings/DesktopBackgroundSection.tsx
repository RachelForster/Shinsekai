import { useEffect, useState } from "react";
import { Bell, Save } from "lucide-react";

import {
  getBackgroundPreferences,
  saveBackgroundPreferences,
  testBedtimeNotification,
  type BackgroundPreferences,
} from "../../shared/desktop/backgroundApi";
import { isTauriDesktop } from "../../shared/desktop/desktopApi";
import { reminderWindow } from "../../shared/desktop/remindersApi";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, Select, Switch, TextInput } from "../../shared/ui";
import { backgroundCopy } from "../../shared/i18n/backgroundCopy";
import { windowCloseCopy } from "../../shared/i18n/windowCloseCopy";
import { closePreferenceChangedEvent } from "../../shared/desktop/windowCloseApi";

export function DesktopBackgroundSection() {
  return isTauriDesktop() ? <BackgroundSettings /> : null;
}

function BackgroundSettings() {
  const { language } = useI18n();
  const copy = backgroundCopy[language];
  const closeCopy = windowCloseCopy[language];
  const [draft, setDraft] = useState<BackgroundPreferences | null>(null);
  const [trayAvailable, setTrayAvailable] = useState(false);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    let stopped = false;
    setError("");
    void getBackgroundPreferences().then(
      (status) => {
        if (stopped) return;
        setDraft(status.preferences);
        setTrayAvailable(status.trayAvailable);
      },
      (error: unknown) => {
        if (!stopped) setError(error instanceof Error ? error.message : String(error));
      },
    );
    return () => {
      stopped = true;
    };
  }, [loadAttempt]);

  useEffect(() => {
    let stopped = false;
    const refreshClosePreference = () => {
      void getBackgroundPreferences()
        .then((status) => {
          if (stopped) return;
          setDraft((current) =>
            current
              ? {
                  ...current,
                  closeToTray: status.preferences.closeToTray,
                  rememberCloseAction: status.preferences.rememberCloseAction,
                }
              : current,
          );
        })
        .catch((reason: unknown) => {
          if (!stopped) setError(String(reason));
        });
    };
    window.addEventListener(closePreferenceChangedEvent, refreshClosePreference);
    return () => {
      stopped = true;
      window.removeEventListener(closePreferenceChangedEvent, refreshClosePreference);
    };
  }, []);

  const edit = (update: Partial<BackgroundPreferences>) => {
    setDraft((current) => (current ? { ...current, ...update } : current));
    setMessage("");
    setError("");
  };

  const runAction = async (action: "save" | "test") => {
    if (!draft || busy) return;
    setMessage("");
    setError("");
    if (action === "save" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.bedtimeTime)) {
      setError(copy.invalidTime);
      return;
    }
    setBusy(action);
    try {
      if (action === "save") {
        const status = await saveBackgroundPreferences({ ...draft, language });
        setDraft(status.preferences);
        setTrayAvailable(status.trayAvailable);
        setMessage(copy.saved);
      } else {
        await testBedtimeNotification(language);
        setMessage(copy.tested);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="section desktop-background-settings page-section-anchor" id="system-background">
      <div className="section__header">
        <h2 className="section__title">{copy.title}</h2>
        <div className="section__actions">
          <Button onClick={() => void reminderWindow("open").catch((reason: unknown) => setError(String(reason)))}>
            {copy.panel}
          </Button>
          <AsyncButton
            disabled={!draft || busy !== null}
            loading={busy === "test"}
            icon={<Bell aria-hidden className="button__icon" />}
            onClick={() => void runAction("test")}
          >
            {copy.test}
          </AsyncButton>
          <AsyncButton
            disabled={!draft || busy !== null}
            loading={busy === "save"}
            variant="primary"
            icon={<Save aria-hidden className="button__icon" />}
            onClick={() => void runAction("save")}
          >
            {copy.save}
          </AsyncButton>
        </div>
      </div>
      {draft ? (
        <>
          <div className="desktop-background-settings__switches">
            <div className="field-row">
              <label className="field-row__label-text" htmlFor="desktop-close-behavior">
                {closeCopy.behavior}
              </label>
              <Select
                id="desktop-close-behavior"
                value={!draft.rememberCloseAction ? "ask" : draft.closeToTray ? "tray" : "exit"}
                disabled={busy !== null}
                onChange={(event) =>
                  edit({
                    rememberCloseAction: event.target.value !== "ask",
                    closeToTray: event.target.value === "tray",
                  })
                }
              >
                <option value="ask">{closeCopy.ask}</option>
                <option value="tray" disabled={!trayAvailable}>
                  {closeCopy.tray}
                </option>
                <option value="exit">{closeCopy.exit}</option>
              </Select>
            </div>
            <Switch
              checked={draft.minimizeToTray}
              disabled={busy !== null || !trayAvailable}
              onChange={(event) => edit({ minimizeToTray: event.target.checked })}
            >
              {copy.minimize}
            </Switch>
          </div>
          <p className="field-row__help">{trayAvailable ? copy.trayHint : copy.unavailable}</p>
          <Switch
            checked={draft.bedtimeEnabled}
            disabled={busy !== null}
            onChange={(event) => edit({ bedtimeEnabled: event.target.checked })}
          >
            {copy.enabled}
          </Switch>
          <div className="field-row">
            <label className="field-row__label-text" htmlFor="desktop-bedtime-time">
              {copy.time}
            </label>
            <TextInput
              id="desktop-bedtime-time"
              type="time"
              value={draft.bedtimeTime}
              required
              disabled={busy !== null || !draft.bedtimeEnabled}
              onChange={(event) => edit({ bedtimeTime: event.target.value })}
            />
          </div>
          <p className="field-row__help">{copy.reminderHint}</p>
          <p className="field-row__help">{copy.runningHint}</p>
          <p className="field-row__help">{copy.notificationHint}</p>
        </>
      ) : !error ? (
        <p role="status">{copy.loading}</p>
      ) : null}
      {error ? (
        <div role="alert" className="field-error">
          {error}
          {!draft ? <Button onClick={() => setLoadAttempt((attempt) => attempt + 1)}>{copy.retry}</Button> : null}
        </div>
      ) : null}
      {message ? (
        <p role="status" className="field-row__help">
          {message}
        </p>
      ) : null}
    </section>
  );
}
