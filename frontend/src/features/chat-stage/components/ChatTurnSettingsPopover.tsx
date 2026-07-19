import { useEffect, useState } from "react";
import { Play, X } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { ChatTurnOptions, ChatTurnState } from "../../../shared/platform/types";
import { IconButton, Switch } from "../../../shared/ui";

export function ChatTurnSettingsPopover({
  onCancelBatch,
  onClose,
  onFlushBatch,
  onTurnOptionsChange,
  open,
  turnOptions,
  turnState,
}: {
  onCancelBatch: () => void;
  onClose: () => void;
  onFlushBatch: () => void;
  onTurnOptionsChange: (options: ChatTurnOptions) => void;
  open: boolean;
  turnOptions: ChatTurnOptions;
  turnState: ChatTurnState;
}) {
  const { t } = useI18n();
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(turnState.remainingSeconds);

  useEffect(() => {
    setRemainingSeconds(turnState.remainingSeconds);
  }, [turnState.remainingSeconds]);

  useEffect(() => {
    if (!open || !turnState.scheduled || remainingSeconds == null || remainingSeconds <= 0) {
      return;
    }
    const timer = window.setTimeout(
      () => setRemainingSeconds((current) => (current == null ? null : Math.max(0, current - 1))),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [open, remainingSeconds, turnState.scheduled]);

  if (!open) {
    return null;
  }

  return (
    <section
      aria-label={t("chat.input.settings")}
      className="dialog-stage-controls__chat-settings"
      id="chat-turn-settings-popover"
      role="dialog"
    >
      <header className="dialog-stage-controls__chat-settings-header">
        <strong>{t("chat.input.settings")}</strong>
        <IconButton className="dialog-stage-controls__chat-settings-close" label={t("common.close")} onClick={onClose}>
          <X aria-hidden />
        </IconButton>
      </header>
      <div className="dialog-stage-controls__chat-settings-options">
        <Switch
          checked={turnOptions.batchEnabled}
          className="dialog-stage-controls__chat-setting"
          id="chat-turn-settings-batch"
          onChange={(event) => onTurnOptionsChange({ ...turnOptions, batchEnabled: event.currentTarget.checked })}
        >
          {t("chat.config.batchEnabled")}
        </Switch>
        <Switch
          checked={turnOptions.interruptEnabled}
          className="dialog-stage-controls__chat-setting"
          id="chat-turn-settings-interrupt"
          onChange={(event) => onTurnOptionsChange({ ...turnOptions, interruptEnabled: event.currentTarget.checked })}
        >
          {t("chat.config.interruptEnabled")}
        </Switch>
      </div>
      {turnOptions.batchEnabled && turnState.pendingCount > 0 ? (
        <div className="dialog-stage-controls__batch-row">
          <span className="dialog-stage-controls__batch-status" role="status">
            {turnState.typing
              ? t("chat.input.batchWaiting", { count: turnState.pendingCount })
              : t("chat.input.batchCountdown", {
                  count: turnState.pendingCount,
                  seconds: remainingSeconds ?? turnOptions.batchIdleSeconds,
                })}
          </span>
          <div className="dialog-stage-controls__batch-actions">
            <IconButton label={t("chat.input.batchSendNow")} onClick={onFlushBatch}>
              <Play aria-hidden />
            </IconButton>
            <IconButton label={t("chat.input.batchCancel")} onClick={onCancelBatch}>
              <X aria-hidden />
            </IconButton>
          </div>
        </div>
      ) : null}
    </section>
  );
}
