import { useEffect, useId, useMemo, useState } from "react";
import { GitFork, RotateCcw } from "lucide-react";

import type { ChatHistoryEntry } from "../../../shared/platform/types";
import { Button } from "../../../shared/ui";
import { useI18n } from "../../../shared/i18n";
import { ChatStageModal } from "./ChatStageModal";

const defaultUserDisplayName = "你";
const hiddenSystemHistorySpeakers = new Set(["scene", "场景", "bgm"]);
const historyRenderBatchSize = 120;

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

function normalizeHistorySearch(value: string) {
  return value.trim().toLocaleLowerCase();
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
  const [query, setQuery] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(historyRenderBatchSize);

  useEffect(() => {
    if (open) {
      setVisibleLimit(historyRenderBatchSize);
    }
  }, [open, query]);

  const roleLabels = useMemo<Record<ChatHistoryEntry["role"], string>>(
    () => ({
      assistant: t("chat.history.role.assistant"),
      options: t("chat.history.role.options"),
      system: t("chat.history.role.system"),
      user: t("chat.history.role.user"),
    }),
    [t],
  );
  const normalizedQuery = normalizeHistorySearch(query);
  const visibleEntries = useMemo(() => {
    const mapped = entries.map((entry) => {
      const dialog = splitHistoryEntryText(entry, userDisplayName, roleLabels);
      return {
        dialog,
        entry,
        localTime: dialog.localTime || historyEntryLocalTime(entry),
      };
    });
    return mapped
      .filter(({ dialog, entry }) => !isHiddenSystemHistoryEntry(entry, dialog))
      .filter(({ dialog, entry }) => {
        if (!normalizedQuery) {
          return true;
        }
        const haystack = `${dialog.speaker} ${dialog.body} ${roleLabels[entry.role]}`.toLocaleLowerCase();
        return haystack.includes(normalizedQuery);
      });
  }, [entries, normalizedQuery, roleLabels, userDisplayName]);
  const renderedEntries = visibleEntries.slice(0, visibleLimit);
  const moreEntriesAvailable = renderedEntries.length < visibleEntries.length;

  if (!open) {
    return null;
  }

  return (
    <ChatStageModal
      backdropClassName="chat-history-backdrop"
      closeLabel={t("common.close")}
      dialogClassName="chat-history-dialog"
      eyebrow="LOG"
      labelledBy={titleId}
      onClose={onClose}
      open={open}
      summary={t("chat.history.count", { count: visibleEntries.length })}
      title={t("chat.history.title")}
    >
      <div className="chat-stage-modal__body chat-history-dialog__body">
        <div className="chat-history__filters">
          <input
            aria-label={t("chat.history.search")}
            className="chat-history__search"
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("chat.history.search")}
            type="search"
            value={query}
          />
          <span className="chat-history__visible-count">
            {t("chat.history.visibleCount", {
              total: visibleEntries.length,
              visible: Math.min(renderedEntries.length, visibleEntries.length),
            })}
          </span>
        </div>
        {loading ? <p className="chat-history__empty">{t("chat.history.loading")}</p> : null}
        {!loading && visibleEntries.length === 0 ? (
          <p className="chat-history__empty">{t("chat.history.empty")}</p>
        ) : null}
        {!loading && visibleEntries.length > 0 ? (
          <div className="chat-history__list">
            {renderedEntries.map(({ dialog, entry, localTime }, index) => {
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
                      <span className="chat-history__index">{t("chat.history.entryIndex", { index: index + 1 })}</span>
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
            {moreEntriesAvailable ? (
              <Button
                className="chat-history__show-more"
                onClick={() => setVisibleLimit((current) => current + historyRenderBatchSize)}
              >
                {t("chat.history.showMore", { count: visibleEntries.length - renderedEntries.length })}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
      <footer className="chat-stage-modal__footer chat-history-dialog__footer">
        <Button onClick={onRefresh}>{t("common.refresh")}</Button>
        <Button onClick={onClose}>{t("common.close")}</Button>
      </footer>
    </ChatStageModal>
  );
}
