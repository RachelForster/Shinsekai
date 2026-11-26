import type { MouseEvent } from "react";
import { Check, Play, RotateCcw, Save } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { ChatHistoryEntry } from "../../../shared/platform/types";
import { Button } from "../../../shared/ui";
import { historyEntryTone, type HistoryRowDialog } from "./historyEntries";

interface HistoryEntryCardProps {
  anchored: boolean;
  checked: boolean;
  dialog: HistoryRowDialog;
  disabled: boolean;
  entry: ChatHistoryEntry;
  localTime: string;
  multi: boolean;
  onReplayVoice: (voiceId: string) => void;
  onRevert: (userIndex: number) => void;
  onSaveVoice: (voiceId: string) => void;
  onSelect?: (event: MouseEvent<HTMLElement>, entryId: string) => void;
  originalIndex: number;
  roleLabel: string;
}

export function HistoryEntryCard({
  anchored,
  checked,
  dialog,
  disabled,
  entry,
  localTime,
  multi,
  onReplayVoice,
  onRevert,
  onSaveVoice,
  onSelect,
  originalIndex,
  roleLabel,
}: HistoryEntryCardProps) {
  const { t } = useI18n();

  return (
    <section
      data-history-entry-id={entry.id}
      data-history-selected={multi && checked ? "true" : undefined}
      data-history-anchor={anchored ? "true" : undefined}
      className="chat-history__entry"
      data-role={entry.role}
      data-tone={historyEntryTone(entry.role)}
      onClick={onSelect ? (event) => onSelect(event, entry.id) : undefined}
    >
      {multi && (
        <button
          aria-checked={checked}
          aria-label={t("chat.history.selection.message", { index: originalIndex + 1 })}
          className="chat-history__checkbox"
          disabled={disabled}
          role="checkbox"
          type="button"
        >
          {checked && <Check aria-hidden size={15} />}
        </button>
      )}
      <header className="chat-history__entry-header">
        <div className="chat-history__nameplate">
          <span aria-hidden className="chat-history__nameplate-accent" />
          <span className="chat-history__speaker">{dialog.speaker}</span>
          <span className="chat-history__role">{roleLabel}</span>
        </div>
        <div className="chat-history__meta">
          <span className="chat-history__index">{t("chat.history.entryIndex", { index: originalIndex + 1 })}</span>
          {localTime ? (
            <time className="chat-history__time" dateTime={new Date(entry.createdAt ?? 0).toISOString()}>
              {localTime}
            </time>
          ) : null}
        </div>
      </header>
      <p className="chat-history__text">{dialog.body}</p>
      {!multi && (entry.voiceId || (entry.role === "user" && entry.revertUserIndex != null)) && (
        <div className="chat-history__actions">
          {entry.voiceId ? (
            <>
              <Button
                className="chat-history__voice-button"
                icon={<Play aria-hidden className="button__icon" />}
                onClick={() => onReplayVoice(entry.voiceId!)}
              >
                {t("chat.history.replayVoice")}
              </Button>
              <Button
                className="chat-history__voice-button"
                icon={<Save aria-hidden className="button__icon" />}
                onClick={() => onSaveVoice(entry.voiceId!)}
              >
                {t("chat.history.saveVoice")}
              </Button>
            </>
          ) : null}
          {entry.role === "user" && entry.revertUserIndex != null ? (
            <Button
              className="chat-history__revert"
              icon={<RotateCcw aria-hidden className="button__icon" />}
              onClick={() => onRevert(entry.revertUserIndex!)}
            >
              {t("chat.history.revert")}
            </Button>
          ) : null}
        </div>
      )}
    </section>
  );
}
