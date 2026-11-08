import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Clapperboard, Copy, GitFork, Play, RotateCcw, Save, Trash2 } from "lucide-react";

import type { ChatHistoryEntry, ChatReplaySnapshot } from "../../../shared/platform/types";
import { prepareChatReplay, startChatReplay, cancelChatReplay } from "../../../entities/chat/repository";
import type { ActiveReplay } from "../replay/ReplayControls";
import "../replay/replay.css";
import { Button, Switch } from "../../../shared/ui";
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
  onClear,
  onClose,
  onCopy,
  onFork,
  onRefresh,
  onReplayVoice,
  onRevert,
  onSaveVoice,
  onToggleVoiceArchive,
  open,
  userDisplayName,
  voiceArchiveEnabled,
  onStartReplay,
  replayDisabled = false,
  onVoiceSettings,
}: {
  onStartReplay?: (replay: ActiveReplay) => void;
  replayDisabled?: boolean;
  onVoiceSettings?: () => void;
  entries: ChatHistoryEntry[];
  forkEnabled: boolean;
  loading: boolean;
  onClear: () => void;
  onClose: () => void;
  onCopy: () => void;
  onFork: (userIndex: number) => void;
  onRefresh: () => void;
  onReplayVoice: (voiceId: string) => void;
  onRevert: (userIndex: number) => void;
  onSaveVoice: (voiceId: string) => void;
  onToggleVoiceArchive: (enabled: boolean) => void;
  open: boolean;
  userDisplayName: string;
  voiceArchiveEnabled: boolean;
}) {
  const { t } = useI18n();
  const titleId = useId();
  const [query, setQuery] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(historyRenderBatchSize);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<number | null>(null);
  const replayTriggerRef = useRef<string | null>(null);
  const restoreFocusRef = useRef(false);
  const [prepared, setPrepared] = useState<ChatReplaySnapshot | null>(null);
  const [range, setRange] = useState<[number, number]>([0, 0]);
  const [pick, setPick] = useState<"start" | "end" | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [replayError, setReplayError] = useState("");
  const requestRef = useRef(0);
  const preparedRef = useRef(prepared);
  preparedRef.current = prepared;
  useEffect(
    () => () => {
      requestRef.current++;
      if (preparedRef.current) void cancelChatReplay(preparedRef.current.id).catch(() => {});
    },
    [],
  );
  const cancelPreparation = () => {
    requestRef.current++;
    if (prepared) void cancelChatReplay(prepared.id).catch(() => {});
    setPrepared(null);
    setPick(null);
    setPreparing(false);
    setReplayError("");
  };
  const close = () => {
    cancelPreparation();
    onClose();
  };
  const prepare = async (entry?: ChatHistoryEntry) => {
    if (preparing || replayDisabled) return;
    const request = ++requestRef.current;
    replayTriggerRef.current = entry?.id ?? null;
    setPreparing(true);
    setReplayError("");
    try {
      const snapshot = await prepareChatReplay();
      if (request !== requestRef.current) {
        void cancelChatReplay(snapshot.id).catch(() => {});
        return;
      }
      const start = entry ? snapshot.entries.findIndex((item) => item.id === entry.id && item.text === entry.text) : 0;
      if (start < 0 || !snapshot.entries.length) {
        void cancelChatReplay(snapshot.id).catch(() => {});
        throw new Error(t("chat.replay.changed"));
      }
      setPrepared(snapshot);
      setRange([start, snapshot.entries.length - 1]);
      setPick(null);
    } catch (error) {
      if (request === requestRef.current) setReplayError(error instanceof Error ? error.message : String(error));
    } finally {
      if (request === requestRef.current) setPreparing(false);
    }
  };
  const begin = async (generate: boolean) => {
    if (!prepared || preparing || replayDisabled) return;
    const request = ++requestRef.current;
    setPreparing(true);
    setReplayError("");
    try {
      const selected = prepared.entries.slice(range[0], range[1] + 1);
      await startChatReplay(prepared.id, selected[0].key, selected.at(-1)!.key, generate);
      if (request !== requestRef.current) return;
      setPrepared(null);
      preparedRef.current = null;
      restoreFocusRef.current = true;
      onStartReplay?.({ snapshot: { ...prepared, entries: selected }, generate });
    } catch (error) {
      if (request === requestRef.current) setReplayError(error instanceof Error ? error.message : String(error));
    } finally {
      if (request === requestRef.current) setPreparing(false);
    }
  };
  const selected = prepared?.entries.slice(range[0], range[1] + 1) ?? [];
  const voiced = selected.filter((entry) => entry.voiceUrls.length).length;
  const generatable = selected.filter((entry) => entry.canGenerate && !entry.voiceUrls.length).length;

  useEffect(() => {
    if (open) {
      setVisibleLimit(historyRenderBatchSize);
    }
  }, [query]);

  useEffect(() => {
    if (!open || loading) {
      return;
    }
    // Open on the newest messages (bottom) rather than the oldest (top).
    // The scroll container is the modal body (overflow: auto), not the list.
    const frame = requestAnimationFrame(() => {
      const body = bodyRef.current;
      if (body) {
        body.scrollTop = scrollRef.current ?? body.scrollHeight;
        if (restoreFocusRef.current) {
          restoreFocusRef.current = false;
          const entry = Array.from(body.querySelectorAll<HTMLElement>("[data-history-entry-id]")).find(
            (element) => element.dataset.historyEntryId === replayTriggerRef.current,
          );
          const target =
            entry?.querySelector<HTMLButtonElement>("[data-replay-start]") ??
            body.querySelector<HTMLInputElement>("input");
          target?.focus({ preventScroll: true });
        }
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [open, loading]);

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
    const mapped = (prepared?.entries ?? entries).map((entry) => {
      const dialog = splitHistoryEntryText(entry, userDisplayName, roleLabels);
      return {
        dialog,
        entry,
        localTime: dialog.localTime || historyEntryLocalTime(entry),
      };
    });
    return mapped
      .filter(({ dialog, entry }) => !isHiddenSystemHistoryEntry(entry, dialog))
      .map((item, originalIndex) => ({ ...item, originalIndex }))
      .filter(({ dialog, entry }) => {
        if (!normalizedQuery) {
          return true;
        }
        const haystack = `${dialog.speaker} ${dialog.body} ${roleLabels[entry.role]}`.toLocaleLowerCase();
        return haystack.includes(normalizedQuery);
      });
  }, [entries, prepared, normalizedQuery, roleLabels, userDisplayName]);
  // Render the newest `visibleLimit` entries so the dialog opens on the latest
  // messages; "show more" then reveals older entries above.
  const hiddenOlderCount = Math.max(0, visibleEntries.length - visibleLimit);
  const renderedEntries = visibleEntries.slice(hiddenOlderCount);
  const moreEntriesAvailable = hiddenOlderCount > 0;

  if (!open) {
    return null;
  }

  return (
    <ChatStageModal
      backdropClassName="chat-history-backdrop"
      closeLabel={t("common.close")}
      dialogClassName="chat-history-dialog"
      eyebrow={t("chat.actionBar.history")}
      headerActions={
        <>
          {onStartReplay && (
            <Button
              disabled={replayDisabled || preparing || loading || !entries.length || Boolean(prepared)}
              onClick={() => void prepare()}
            >
              {t("chat.replay.fromStart")}
            </Button>
          )}
          <div className="chat-history__voice-toggle">
            <label htmlFor="chat-history-voice-archive">{t("chat.history.voiceArchive")}</label>
            <Switch
              disabled={Boolean(prepared)}
              checked={voiceArchiveEnabled}
              id="chat-history-voice-archive"
              onChange={(event) => onToggleVoiceArchive(event.target.checked)}
            />
          </div>
          <Button
            aria-label={t("chat.toolbar.copyHistory")}
            className="chat-history__header-action"
            icon={<Copy aria-hidden className="button__icon" />}
            onClick={onCopy}
          >
            {t("chat.actionBar.copy")}
          </Button>
          <Button
            disabled={Boolean(prepared)}
            aria-label={t("chat.toolbar.clearHistory")}
            className="chat-history__header-action"
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={onClear}
            variant="danger"
          >
            {t("chat.actionBar.clear")}
          </Button>
        </>
      }
      labelledBy={titleId}
      onClose={close}
      open={open}
      summary={t("chat.history.count", { count: visibleEntries.length })}
      title={t("chat.history.title")}
    >
      <div
        className="chat-stage-modal__body chat-history-dialog__body"
        ref={bodyRef}
        onScroll={(event) => {
          scrollRef.current = event.currentTarget.scrollTop;
        }}
      >
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
            {moreEntriesAvailable ? (
              <Button
                className="chat-history__show-more"
                onClick={() => setVisibleLimit((current) => current + historyRenderBatchSize)}
              >
                {t("chat.history.showMore", { count: hiddenOlderCount })}
              </Button>
            ) : null}
            {renderedEntries.map(({ dialog, entry, localTime, originalIndex }) => {
              return (
                <section
                  data-history-entry-id={entry.id}
                  data-replay-boundary={
                    prepared &&
                    (prepared.entries[range[0]].id === entry.id || prepared.entries[range[1]].id === entry.id)
                      ? "true"
                      : undefined
                  }
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
                        {t("chat.history.entryIndex", { index: originalIndex + 1 })}
                      </span>
                      {localTime ? (
                        <time className="chat-history__time" dateTime={new Date(entry.createdAt ?? 0).toISOString()}>
                          {localTime}
                        </time>
                      ) : null}
                    </div>
                  </header>
                  <p className="chat-history__text">{dialog.body}</p>
                  <div className="chat-history__actions">
                    {onStartReplay && (
                      <>
                        {!prepared ? (
                          <Button
                            data-replay-start
                            className="chat-history__replay"
                            icon={<Clapperboard aria-hidden className="button__icon" />}
                            disabled={replayDisabled || preparing}
                            onClick={() => void prepare(entry)}
                          >
                            {t("chat.replay.fromHere")}
                          </Button>
                        ) : (
                          pick && (
                            <Button
                              disabled={
                                preparing ||
                                (pick === "end" &&
                                  prepared.entries.findIndex((item) => item.id === entry.id) < range[0])
                              }
                              onClick={() => {
                                const position = prepared.entries.findIndex((item) => item.id === entry.id);
                                setRange(
                                  pick === "end"
                                    ? [range[0], position]
                                    : [position, position > range[1] ? prepared.entries.length - 1 : range[1]],
                                );
                                setPick(null);
                              }}
                            >
                              {t(pick === "end" ? "chat.replay.endHere" : "chat.replay.startHere")}
                            </Button>
                          )
                        )}
                      </>
                    )}
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
                      <>
                        {forkEnabled ? (
                          <Button
                            disabled={Boolean(prepared)}
                            className="chat-history__fork"
                            icon={<GitFork aria-hidden className="button__icon" />}
                            onClick={() => onFork(entry.revertUserIndex!)}
                          >
                            {t("chat.history.fork")}
                          </Button>
                        ) : null}
                        <Button
                          disabled={Boolean(prepared)}
                          className="chat-history__revert"
                          icon={<RotateCcw aria-hidden className="button__icon" />}
                          onClick={() => onRevert(entry.revertUserIndex!)}
                        >
                          {t("chat.history.revert")}
                        </Button>
                      </>
                    ) : null}
                  </div>
                </section>
              );
            })}
          </div>
        ) : null}
      </div>
      <footer className="chat-stage-modal__footer chat-history-dialog__footer">
        {prepared ? (
          <div className="chat-replay-range">
            <p>{t("chat.replay.range", { start: range[0] + 1, end: range[1] + 1, count: selected.length })}</p>
            <div className="chat-replay-bound">
              <span>
                {t("chat.replay.start")}: {prepared.entries[range[0]].text.slice(0, 70)}
              </span>
              <Button disabled={preparing} onClick={() => setPick("start")}>
                {t("chat.replay.changeStart")}
              </Button>
            </div>
            <div className="chat-replay-bound">
              <span>
                {t("chat.replay.end")}: {prepared.entries[range[1]].text.slice(0, 70)}
              </span>
              <Button disabled={preparing} onClick={() => setPick("end")}>
                {t("chat.replay.changeEnd")}
              </Button>
            </div>
            {pick && <p role="status">{t(pick === "end" ? "chat.replay.pickEnd" : "chat.replay.pickStart")}</p>}
            <p>{t("chat.replay.voices", { ready: voiced, missing: generatable })}</p>
            {selected.some((entry) => !entry.frame) && <p>{t("chat.replay.noFrame")}</p>}
            {generatable > 0 ? (
              <p>{t("chat.replay.generateHint")}</p>
            ) : (
              selected.some((entry) => entry.role === "assistant" && !entry.voiceUrls.length && !entry.canGenerate) && (
                <p>
                  {t("chat.replay.noTts")}{" "}
                  {onVoiceSettings && <Button onClick={onVoiceSettings}>{t("chat.replay.settings")}</Button>}
                </p>
              )
            )}
            <div className="chat-replay-range-actions">
              <Button disabled={preparing || replayDisabled} onClick={() => void begin(false)}>
                {t("chat.replay.direct")}
              </Button>
              {generatable > 0 && (
                <Button disabled={preparing || replayDisabled} variant="primary" onClick={() => void begin(true)}>
                  {t("chat.replay.generate")}
                </Button>
              )}
              <Button onClick={cancelPreparation}>{t("common.cancel")}</Button>
            </div>
          </div>
        ) : (
          <>
            <Button onClick={onRefresh}>{t("common.refresh")}</Button>
            <Button onClick={close}>{t("common.close")}</Button>
          </>
        )}
        {preparing && <p role="status">{t("chat.replay.preparing")}</p>}
        {replayDisabled && onStartReplay && <p>{t("chat.replay.busy")}</p>}
        {replayError && <p role="alert">{replayError}</p>}
      </footer>
    </ChatStageModal>
  );
}
