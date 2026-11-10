import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Camera,
  Check,
  Clapperboard,
  Copy,
  GitFork,
  ListChecks,
  Play,
  RotateCcw,
  Save,
  Trash2,
  Video,
} from "lucide-react";

import type { ChatHistoryEntry, ChatReplaySnapshot } from "../../../shared/platform/types";
import { prepareChatReplay, startChatReplay, cancelChatReplay } from "../../../entities/chat/repository";
import type { ActiveReplay } from "../replay/ReplayControls";
import type { RecordingAudio } from "../audio/stageAudioMixer";
import {
  canCaptureReplay,
  renderHistoryScreenshot,
  requestReplayCapture,
  type ReplayCapture,
} from "../replay/historyExport";
import { useHistorySelection } from "../replay/useHistorySelection";
import { Button, Switch } from "../../../shared/ui";
import { useI18n } from "../../../shared/i18n";
import { ChatStageModal } from "./ChatStageModal";

const defaultUserDisplayName = "你";
const hiddenSystemHistorySpeakers = new Set(["scene", "场景", "bgm"]);
const historyRenderBatchSize = 120;

interface HistoryClip {
  mode: "replay" | "video";
  snapshot: ChatReplaySnapshot;
  entries: ChatReplaySnapshot["entries"];
  includesUnselected: boolean;
}

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

function shareableUserText(text: string) {
  return text
    .replace(/^\[[^\]\n]*(?:本地时间|Local time)[^\]\n]*\]\s*/, "")
    .replace(/(?:\s*\[(?:image|file):[^\]\r\n]*\])+\s*$/i, "")
    .trim();
}

function sameHistoryMessage(source: ChatHistoryEntry, target: ChatHistoryEntry) {
  if (
    source.id !== target.id ||
    source.role !== target.role ||
    source.dialogId !== target.dialogId ||
    source.createdAt !== target.createdAt
  ) {
    return false;
  }
  if (source.role !== "user" || source.text === target.text) return source.text === target.text;
  const normalized = (text: string) => {
    const prefix = text.match(/^\s*([^：:\n]{1,120})[：:]\s*/);
    return `${prefix?.[1].trim() ?? ""}:${shareableUserText(text.slice(prefix?.[0].length ?? 0))}`;
  };
  return normalized(source.text) === normalized(target.text);
}

export function HistoryDialog({
  entries,
  forkEnabled,
  loading,
  onClear,
  onClose,
  onExportImage,
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
  recordAudio,
  replayDisabled = false,
}: {
  onStartReplay?: (replay: ActiveReplay) => void;
  recordAudio: () => RecordingAudio;
  replayDisabled?: boolean;
  entries: ChatHistoryEntry[];
  forkEnabled: boolean;
  loading: boolean;
  onClear: () => void;
  onClose: () => void;
  onExportImage: (blob: Blob) => Promise<void>;
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
  const [multi, setMulti] = useState(false);
  const [clip, setClip] = useState<HistoryClip | null>(null);
  const [generate, setGenerate] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [feedback, setFeedback] = useState<{ text: string; error?: boolean }>();
  const requestRef = useRef(0);
  const planRef = useRef<string>();
  useEffect(
    () => () => {
      requestRef.current++;
      if (planRef.current) void cancelChatReplay(planRef.current).catch(() => {});
    },
    [],
  );
  const clearClip = () => {
    requestRef.current++;
    if (planRef.current) void cancelChatReplay(planRef.current).catch(() => {});
    planRef.current = undefined;
    setClip(null);
    setGenerate(false);
    setPreparing(false);
    setFeedback(undefined);
  };
  const close = () => {
    clearClip();
    setMulti(false);
    selection.reset();
    onClose();
  };
  const prepare = async (mode: HistoryClip["mode"]) => {
    if (preparing || replayDisabled || !selectedRows.length) return;
    clearClip();
    const request = ++requestRef.current;
    setPreparing(true);
    try {
      const snapshot = await prepareChatReplay();
      if (request !== requestRef.current) {
        void cancelChatReplay(snapshot.id).catch(() => {});
        return;
      }
      planRef.current = snapshot.id;
      const first = selectedRows[0];
      const last = selectedRows.at(-1)!;
      const start = snapshot.entries.findIndex((item) => item.id === first.entry.id);
      const end = snapshot.entries.findIndex((item) => item.id === last.entry.id);
      const entries = snapshot.entries.slice(start, end + 1);
      const expected = historyRows.slice(first.originalIndex, last.originalIndex + 1);
      if (
        start < 0 ||
        end < start ||
        entries.length !== expected.length ||
        entries.some((item, index) => !sameHistoryMessage(expected[index].entry, item))
      ) {
        throw new Error(t("chat.replay.changed"));
      }
      setClip({
        mode,
        snapshot,
        entries,
        includesUnselected: entries.some((item) => !selection.selected.has(item.id)),
      });
    } catch (error) {
      if (request === requestRef.current) {
        clearClip();
        setFeedback({ text: String(error instanceof Error ? error.message : error), error: true });
      }
    } finally {
      if (request === requestRef.current) setPreparing(false);
    }
  };
  const begin = async () => {
    if (!clip || preparing || replayDisabled) return;
    const request = ++requestRef.current;
    setPreparing(true);
    setFeedback(undefined);
    let capture: ReplayCapture | undefined;
    try {
      if (clip.mode === "video") {
        const requested = await requestReplayCapture(recordAudio);
        if (!requested) return;
        capture = requested;
      }
      if (request !== requestRef.current) return;
      await startChatReplay(clip.snapshot.id, clip.entries[0].key, clip.entries.at(-1)!.key, generate);
      if (request !== requestRef.current) return;
      planRef.current = undefined;
      setClip(null);
      setMulti(false);
      selection.reset();
      onStartReplay?.({ snapshot: { ...clip.snapshot, entries: clip.entries }, generate, capture });
      capture = undefined;
    } catch (error) {
      if (request === requestRef.current) {
        setFeedback({
          text:
            capture || clip.mode === "replay"
              ? String(error instanceof Error ? error.message : error)
              : t("chat.history.selection.videoFailed"),
          error: true,
        });
      }
    } finally {
      capture?.stop(false);
      if (request === requestRef.current) setPreparing(false);
    }
  };
  const generatable = clip?.entries.some((entry) => entry.canGenerate && !entry.voiceUrls.length);

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
  const historyRows = useMemo(
    () =>
      entries
        .map((entry) => {
          const dialog = splitHistoryEntryText(entry, userDisplayName, roleLabels);
          return { dialog, entry, localTime: dialog.localTime || historyEntryLocalTime(entry) };
        })
        .filter(({ dialog, entry }) => !isHiddenSystemHistoryEntry(entry, dialog))
        .map((item, originalIndex) => ({ ...item, originalIndex })),
    [entries, roleLabels, userDisplayName],
  );
  const rowIds = useMemo(() => historyRows.map(({ entry }) => entry.id), [historyRows]);
  const selection = useHistorySelection(rowIds, bodyRef);
  const previousRows = useRef(historyRows);
  useEffect(() => {
    const previous = previousRows.current;
    previousRows.current = historyRows;
    if (!multi || previous === historyRows) return;
    const changed = previous.some(({ entry, originalIndex }) => {
      if (!selection.selected.has(entry.id)) return false;
      const current = historyRows[originalIndex]?.entry;
      return !current || !sameHistoryMessage(entry, current);
    });
    if (changed) {
      clearClip();
      selection.reset();
      setFeedback({ text: t("chat.replay.changed"), error: true });
    }
  }, [historyRows, multi, selection.selected]);
  const selectedRows = historyRows.filter(({ entry }) => selection.selected.has(entry.id));
  const visibleEntries = useMemo(
    () =>
      historyRows.filter(({ dialog, entry }) =>
        `${dialog.speaker} ${dialog.body} ${roleLabels[entry.role]}`.toLocaleLowerCase().includes(normalizedQuery),
      ),
    [historyRows, normalizedQuery, roleLabels],
  );
  // Render the newest `visibleLimit` entries so the dialog opens on the latest
  // messages; "show more" then reveals older entries above.
  const hiddenOlderCount = Math.max(0, visibleEntries.length - visibleLimit);
  const renderedEntries = visibleEntries.slice(hiddenOlderCount);
  const moreEntriesAvailable = hiddenOlderCount > 0;
  const videoAvailable = canCaptureReplay();

  const toggleMulti = () => {
    clearClip();
    selection.reset();
    setMulti(!multi);
  };
  const exportSelection = async (image: boolean) => {
    const messages = selectedRows.map(({ dialog, entry }) => ({
      speaker: dialog.speaker,
      body: entry.role === "user" ? shareableUserText(dialog.body) : dialog.body,
      user: entry.role === "user",
    }));
    setFeedback(undefined);
    try {
      if (image) {
        const png = await renderHistoryScreenshot(messages, t("chat.history.selection.imageTitle"));
        if (!png) {
          setFeedback({ text: t("chat.history.selection.imageTooLong"), error: true });
          return;
        }
        await onExportImage(png);
      } else {
        await navigator.clipboard.writeText(messages.map(({ speaker, body }) => `${speaker}: ${body}`).join("\n\n"));
        setFeedback({ text: t("chat.history.selection.copied") });
      }
    } catch {
      setFeedback({ text: t("chat.history.selection.exportFailed"), error: true });
    }
  };

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
          {!multi && (
            <div className="chat-history__voice-toggle">
              <label htmlFor="chat-history-voice-archive">{t("chat.history.voiceArchive")}</label>
              <Switch
                checked={voiceArchiveEnabled}
                id="chat-history-voice-archive"
                onChange={(event) => onToggleVoiceArchive(event.target.checked)}
              />
            </div>
          )}
          <Button
            aria-pressed={multi}
            className="chat-history__select-mode"
            disabled={!multi && (loading || !historyRows.length)}
            icon={<ListChecks aria-hidden className="button__icon" />}
            onClick={toggleMulti}
          >
            {t(multi ? "common.cancel" : "chat.history.selection.enter")}
          </Button>
          {!multi && (
            <Button
              aria-label={t("chat.toolbar.clearHistory")}
              className="chat-history__header-action"
              icon={<Trash2 aria-hidden className="button__icon" />}
              onClick={onClear}
              variant="danger"
            >
              {t("chat.actionBar.clear")}
            </Button>
          )}
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
          <div
            className="chat-history__list"
            data-multi={multi || undefined}
            {...(multi && !clip && !preparing ? selection.pointerHandlers : {})}
          >
            {moreEntriesAvailable ? (
              <Button
                className="chat-history__show-more"
                onClick={() => setVisibleLimit((current) => current + historyRenderBatchSize)}
              >
                {t("chat.history.showMore", { count: hiddenOlderCount })}
              </Button>
            ) : null}
            {renderedEntries.map(({ dialog, entry, localTime, originalIndex }) => {
              const checked = selection.selected.has(entry.id);
              return (
                <section
                  data-history-entry-id={entry.id}
                  data-history-selected={multi && checked ? "true" : undefined}
                  data-history-anchor={multi && selection.anchor === entry.id ? "true" : undefined}
                  className="chat-history__entry"
                  data-role={entry.role}
                  data-tone={historyEntryTone(entry.role)}
                  key={entry.id}
                  onClick={
                    multi && !clip && !preparing
                      ? (event) => {
                          if (feedback) setFeedback(undefined);
                          selection.click(event, entry.id);
                        }
                      : undefined
                  }
                >
                  {multi && (
                    <button
                      aria-checked={checked}
                      aria-label={t("chat.history.selection.message", { index: originalIndex + 1 })}
                      className="chat-history__checkbox"
                      disabled={preparing || Boolean(clip)}
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
                        <>
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
                        </>
                      ) : null}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        ) : null}
      </div>
      {multi ? (
        <footer className="chat-history-selection">
          {!clip && selection.anchor && !preparing && (
            <Button
              className="chat-history-selection__to-end"
              icon={<ArrowDownToLine aria-hidden className="button__icon" />}
              onClick={selection.selectToVisibleEnd}
            >
              {t("chat.history.selection.toHere")}
            </Button>
          )}
          {clip ? (
            <>
              <div className="chat-history-selection__summary">
                <strong>
                  {t("chat.replay.range", {
                    start: clip.entries[0].position,
                    end: clip.entries.at(-1)!.position,
                    count: clip.entries.length,
                  })}
                </strong>
                {clip.includesUnselected && <span>{t("chat.history.selection.contiguous")}</span>}
                {clip.mode === "video" && <span>{t("chat.history.selection.videoHint")}</span>}
              </div>
              <div className="chat-history-selection__actions">
                {generatable && (
                  <label className="chat-history-selection__voice">
                    <input
                      checked={generate}
                      disabled={preparing}
                      onChange={(event) => setGenerate(event.target.checked)}
                      type="checkbox"
                    />
                    {t("chat.history.selection.fillVoice")}
                  </label>
                )}
                <Button onClick={clearClip}>{t("chat.history.selection.edit")}</Button>
                <Button
                  className="chat-history-selection__primary"
                  disabled={preparing || replayDisabled}
                  onClick={() => void begin()}
                >
                  {t(clip.mode === "video" ? "chat.history.selection.record" : "chat.replay.direct")}
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="chat-history-selection__summary">
                <strong role="status">{t("chat.history.selection.count", { count: selectedRows.length })}</strong>
                {selectedRows.length === 0 && <span>{t("chat.history.selection.hint")}</span>}
                {selectedRows.length > 0 && replayDisabled && onStartReplay && <span>{t("chat.replay.busy")}</span>}
              </div>
              <div className="chat-history-selection__actions">
                <Button
                  disabled={preparing || visibleEntries.length === 0}
                  onClick={() => selection.reset(visibleEntries.map(({ entry }) => entry.id))}
                >
                  {t("chat.history.selection.all")}
                </Button>
                {onStartReplay && (
                  <Button
                    className="chat-history-selection__primary"
                    disabled={!selectedRows.length || preparing || replayDisabled}
                    icon={<Clapperboard aria-hidden className="button__icon" />}
                    onClick={() => void prepare("replay")}
                  >
                    {t("chat.history.selection.replay")}
                  </Button>
                )}
                <Button
                  disabled={!selectedRows.length || preparing}
                  icon={<Copy aria-hidden className="button__icon" />}
                  onClick={() => void exportSelection(false)}
                >
                  {t("chat.actionBar.copy")}
                </Button>
                <Button
                  disabled={!selectedRows.length || preparing}
                  icon={<Camera aria-hidden className="button__icon" />}
                  onClick={() => void exportSelection(true)}
                >
                  {t("chat.history.selection.screenshot")}
                </Button>
                {onStartReplay && (
                  <Button
                    disabled={!selectedRows.length || preparing || replayDisabled || !videoAvailable}
                    title={videoAvailable ? undefined : t("chat.history.selection.videoUnsupported")}
                    icon={<Video aria-hidden className="button__icon" />}
                    onClick={() => void prepare("video")}
                  >
                    {t("chat.history.selection.video")}
                  </Button>
                )}
              </div>
            </>
          )}
          {preparing && (
            <p className="chat-history-selection__feedback" role="status">
              {t("chat.replay.preparing")}
            </p>
          )}
          {feedback && (
            <p className="chat-history-selection__feedback" role={feedback.error ? "alert" : "status"}>
              {feedback.text}
            </p>
          )}
        </footer>
      ) : (
        <footer className="chat-stage-modal__footer chat-history-dialog__footer">
          <Button onClick={onRefresh}>{t("common.refresh")}</Button>
          <Button onClick={close}>{t("common.close")}</Button>
        </footer>
      )}
    </ChatStageModal>
  );
}
