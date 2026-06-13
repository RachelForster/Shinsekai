import { useEffect, useId, useRef, type KeyboardEvent, type MouseEvent } from "react";
import { RotateCcw, X } from "lucide-react";

import type { ChatHistoryEntry } from "../../../shared/platform/types";
import { Button, IconButton } from "../../../shared/ui";
import { useI18n } from "../../../shared/i18n";

const defaultUserDisplayName = "你";

function normalizeUserDisplayName(value?: string) {
  return value?.trim() || defaultUserDisplayName;
}

function userSpeakerPrefixPattern(userDisplayName: string) {
  const names = [defaultUserDisplayName, userDisplayName]
    .map((name) => name.trim())
    .filter(Boolean)
    .filter((name, index, list) => list.indexOf(name) === index)
    .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`^\\s*(${names.join("|")})\\s*[：:]\\s*([\\s\\S]*)$`);
}

function historySpeakerFallback(role: ChatHistoryEntry["role"], userDisplayName: string) {
  if (role === "user") {
    return userDisplayName;
  }
  if (role === "assistant") {
    return "角色";
  }
  if (role === "options") {
    return "选项";
  }
  return "旁白";
}

function historyEntryLocalTime(entry: ChatHistoryEntry) {
  const raw = entry.createdAt;
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    return "";
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function splitHistoryEntryText(entry: ChatHistoryEntry, userDisplayName: string) {
  const userName = normalizeUserDisplayName(userDisplayName);
  if (entry.role === "user") {
    const userMatch = entry.text.match(userSpeakerPrefixPattern(userName));
    return {
      body: (userMatch?.[2] ?? entry.text).trimStart(),
      localTime: historyEntryLocalTime(entry),
      speaker: userMatch?.[1] === defaultUserDisplayName ? userName : userMatch?.[1]?.trim() || userName,
    };
  }
  const match = entry.text.match(/^\s*([^：:\n]{1,36})\s*[：:]\s*([\s\S]*)$/);
  if (!match) {
    return { body: entry.text, localTime: "", speaker: historySpeakerFallback(entry.role, userName) };
  }
  return {
    body: match[2]?.trimStart() ?? "",
    localTime: "",
    speaker: match[1]?.trim() || historySpeakerFallback(entry.role, userName),
  };
}

export function HistoryDialog({
  entries,
  loading,
  onClose,
  onRefresh,
  onRevert,
  open,
  userDisplayName,
}: {
  entries: ChatHistoryEntry[];
  loading: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onRevert: (userIndex: number) => void;
  open: boolean;
  userDisplayName: string;
}) {
  const { t } = useI18n();
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.setTimeout(() => closeButtonRef.current?.focus(), 0);
    return () => previous?.focus();
  }, [open]);

  if (!open) {
    return null;
  }

  const onBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      onClose();
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
    }
  };

  return (
    <div className="chat-history-backdrop" onMouseDown={onBackdropMouseDown} role="presentation">
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className="chat-history-dialog"
        onKeyDown={onKeyDown}
        role="dialog"
      >
        <header className="chat-history-dialog__header">
          <div className="chat-history-dialog__heading">
            <h2 className="chat-history-dialog__title" id={titleId}>
              {t("chat.history.title")}
            </h2>
          </div>
          <IconButton
            className="chat-history-dialog__close"
            label={t("common.close")}
            onClick={onClose}
            ref={closeButtonRef}
          >
            <X aria-hidden className="icon-button__icon" />
          </IconButton>
        </header>
        <div className="chat-history-dialog__body">
          {loading ? <p className="chat-history__empty">{t("chat.history.loading")}</p> : null}
          {!loading && entries.length === 0 ? <p className="chat-history__empty">{t("chat.history.empty")}</p> : null}
          {!loading && entries.length > 0 ? (
            <div className="chat-history__list">
              {entries.map((entry) => {
                const dialog = splitHistoryEntryText(entry, userDisplayName);
                return (
                  <section className="chat-history__entry" data-role={entry.role} key={entry.id}>
                    <div className="chat-history__speaker-row">
                      <span className="chat-history__speaker">{dialog.speaker}</span>
                      {entry.role === "user" && dialog.localTime ? (
                        <span className="chat-history__time">{dialog.localTime}</span>
                      ) : null}
                    </div>
                    <p className="chat-history__text">{dialog.body}</p>
                    {entry.role === "user" && entry.revertUserIndex != null ? (
                      <div className="chat-history__actions">
                        <Button
                          className="chat-history__revert"
                          icon={<RotateCcw aria-hidden className="button__icon" />}
                          onClick={() => onRevert(entry.revertUserIndex!)}
                        >
                          {t("chat.history.revert")}
                        </Button>
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </div>
          ) : null}
        </div>
        <footer className="chat-history-dialog__footer">
          <Button onClick={onRefresh}>{t("common.refresh")}</Button>
          <Button onClick={onClose}>{t("common.close")}</Button>
        </footer>
      </section>
    </div>
  );
}
