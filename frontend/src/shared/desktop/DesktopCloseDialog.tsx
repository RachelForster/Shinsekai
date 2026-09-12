import { useEffect, useRef, useState } from "react";

import { useI18n } from "../i18n";
import { Button, Dialog } from "../ui";
import { getCloseRequestStatus, onCloseRequested, resolveCloseRequest, type CloseAction } from "./windowCloseApi";
import "./DesktopCloseDialog.css";

export function DesktopCloseDialog() {
  const { t } = useI18n();
  const [status, setStatus] = useState({ requested: false, trayAvailable: false });
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const acting = useRef(false);

  useEffect(() => {
    let stopped = false;
    let revision = 0;
    let dispose: (() => void) | undefined;
    void (async () => {
      dispose = await onCloseRequested((next) => {
        revision += 1;
        if (!stopped && !acting.current) setStatus(next);
      });
      if (stopped) return dispose();
      const before = revision;
      const pending = await getCloseRequestStatus();
      if (!stopped && before === revision && !acting.current) setStatus(pending);
    })().catch((reason: unknown) => {
      console.error("Desktop close listener failed", reason);
    });
    return () => {
      stopped = true;
      dispose?.();
    };
  }, []);

  const choose = async (action: CloseAction) => {
    if (acting.current) return;
    acting.current = true;
    setBusy(true);
    setError("");
    try {
      await resolveCloseRequest(action, action !== "cancel" && remember);
      setStatus((current) => ({ ...current, requested: false }));
      setRemember(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      acting.current = false;
      setBusy(false);
    }
  };

  return (
    <Dialog
      className="desktop-close-dialog"
      title={t("desktop.windowClose.title")}
      open={status.requested}
      dismissible={!busy}
      closeLabel={t("desktop.windowClose.cancel")}
      onClose={() => void choose("cancel")}
      footer={
        <>
          <Button disabled={busy} onClick={() => void choose("cancel")}>
            {t("desktop.windowClose.cancel")}
          </Button>
          <Button disabled={busy} variant="danger" onClick={() => void choose("exit")}>
            {t("desktop.windowClose.exit")}
          </Button>
          <Button disabled={busy || !status.trayAvailable} variant="primary" onClick={() => void choose("tray")}>
            {t("desktop.windowClose.tray")}
          </Button>
        </>
      }
    >
      <p>{t("desktop.windowClose.body")}</p>
      {!status.trayAvailable ? <p className="field-row__help">{t("desktop.windowClose.unavailable")}</p> : null}
      <label className="desktop-close-dialog__remember">
        <input
          type="checkbox"
          checked={remember}
          disabled={busy}
          onChange={(event) => setRemember(event.target.checked)}
        />
        {t("desktop.windowClose.remember")}
      </label>
      <p className="field-row__help">{t("desktop.windowClose.hint")}</p>
      {error ? (
        <p role="alert" className="field-error">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}
