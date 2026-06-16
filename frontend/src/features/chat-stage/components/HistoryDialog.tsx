import { useEffect, useId, useRef, type KeyboardEvent, type MouseEvent } from "react";
import { GitFork, RotateCcw, X } from "lucide-react";

import type { ChatHistoryEntry } from "../../../shared/platform/types";
import { Button, IconButton } from "../../../shared/ui";
import { useI18n } from "../../../shared/i18n";

const defaultUserDisplayName = "你";
const hiddenSystemHistorySpeakers = new Set(["scene", "场景", "bgm"]);

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

function historySpeakerFallback(
  role: ChatHistoryEntry["role"],
  userDisplayName: string,
  labels: Record<ChatHistoryEntry["role"], string>,
) {
  if (role === "user") {
    return userDisplayName;
  }
  return labels[role] ?? labels.system;
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

function splitHistoryEntryText(
  entry: ChatHistoryEntry,
  userDisplayName: string,
  labels: Record<ChatHistoryEntry["role"], string>,
) {
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
    return { body: entry.text, localTime: "", speaker: historySpeakerFallback(entry.role, userName, labels) };
  }
  return {
    body: match[2]?.trimStart() ?? "",
    localTime: "",
    speaker: match[1]?.trim() || historySpeakerFallback(entry.role, userName, labels),
  };
}

function historyEntryTone(role: ChatHistoryEntry["role"]) {
  if (role === "user") {
    return "user";
  }
  if (role === "options") {
    return "options";
  }
  if (role === "system") {
    return "system";
  }
  return "assistant";
}

function normalizeHistorySpeaker(value: string) {
  return value.trim().toLocaleLowerCase();
}

function isHiddenSystemHistoryEntry(entry: ChatHistoryEntry, dialog: { speaker: string }) {
  if (entry.role !== "system") {
    return false;
  }
  if (hiddenSystemHistorySpeakers.has(normalizeHistorySpeaker(dialog.speaker))) {
    return true;
  }
  return /^\s*(?:scene|场景|bgm)\s*[：:]/i.test(entry.text);
}

export function HistoryDialog({
  entries,
  forkEnabled,
  loading,
  onClose,
  onFork,
  onRefresh,
  onRevert,
  open,
  userDisplayName,
}: {
  entries: ChatHistoryEntry[];
  forkEnabled: boolean;
  loading: boolean;
  onClose: () => void;
  onFork: (userIndex: number) => void;
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
  const roleLabels: Record<ChatHistoryEntry["role"], string> = {
    assistant: t("chat.history.role.assistant"),
    options: t("chat.history.role.options"),
    system: t("chat.history.role.system"),
    user: t("chat.history.role.user"),
  };
  const visibleEntries = entries
    .map((entry) => {
      const dialog = splitHistoryEntryText(entry, userDisplayName, roleLabels);
      return {
        dialog,
        entry,
        localTime: dialog.localTime || historyEntryLocalTime(entry),
      };
    })
    .filter(({ dialog, entry }) => !isHiddenSystemHistoryEntry(entry, dialog));

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
            <span className="chat-history-dialog__eyebrow">LOG</span>
            <h2 className="chat-history-dialog__title" id={titleId}>
              {t("chat.history.title")}
            </h2>
            <p className="chat-history-dialog__summary">{t("chat.history.count", { count: visibleEntries.length })}</p>
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
          {!loading && visibleEntries.length === 0 ? (
            <p className="chat-history__empty">{t("chat.history.empty")}</p>
          ) : null}
          {!loading && visibleEntries.length > 0 ? (
            <div className="chat-history__list">
              {visibleEntries.map(({ dialog, entry, localTime }, index) => {
                return (
                  <section
                    className="chat-history__entry"
                    data-role={entry.role}
                    data-tone={historyEntryTone(entry.role)}
                    key={entry.id}
                  >
                    <header className="chat-history__entry-header">
                      <div className="chat-history__nameplate">
                        <span aria-hidden className="chat-history__nameplate-accent" />
                        <span className="chat-history__speaker">{dialog.speaker}</span>
                        <span className="chat-history__role">{roleLabels[entry.role]}</span>
                      </div>
                      <div className="chat-history__meta">
                        <span className="chat-history__index">
                          {t("chat.history.entryIndex", { index: index + 1 })}
                        </span>
                        {localTime ? (
                          <time className="chat-history__time" dateTime={new Date(entry.createdAt ?? 0).toISOString()}>
                            {localTime}
                          </time>
                        ) : null}
                      </div>
                    </header>
                    <p className="chat-history__text">{dialog.body}</p>
                    {entry.role === "user" && entry.revertUserIndex != null ? (
                      <div className="chat-history__actions">
                        {forkEnabled ? (
                          <Button
                            className="chat-history__fork"
                            icon={<GitFork aria-hidden className="button__icon" />}
                            onClick={() => onFork(entry.revertUserIndex!)}
                          >
                            {t("chat.history.fork")}
                          </Button>
                        ) : null}
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
