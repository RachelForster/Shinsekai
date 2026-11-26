import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ListChecks, Trash2 } from "lucide-react";

import type { ChatHistoryEntry, ChatVnExportAnchor } from "../../../shared/platform/types";
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
import { VnExportDialog } from "../replay/VnExportDialog";
import { Button, Switch } from "../../../shared/ui";
import { useI18n } from "../../../shared/i18n";
import { ChatStageModal } from "./ChatStageModal";
import { HistoryEntryCard } from "./HistoryEntryCard";
import { HistorySelectionFooter, type HistoryClip } from "./HistorySelectionFooter";
import {
  historyEntryLocalTime,
  historyRenderBatchSize,
  isHiddenSystemHistoryEntry,
  normalizeHistorySearch,
  sameHistoryMessage,
  shareableUserText,
  splitHistoryEntryText,
} from "./historyEntries";

interface VnExportSelectionSnapshot {
  expectedSessionId?: string;
  selectedEntryIds: string[];
  selectedEntryAnchors: ChatVnExportAnchor[];
  startEntryId?: string;
  endEntryId?: string;
  rangeCount: number;
}

export function HistoryDialog({
  entries,
  loading,
  onClear,
  onClose,
  onExportImage,
  onRefresh,
  onReplayVoice,
  onRevert,
  onSaveVoice,
  onToggleVoiceArchive,
  open,
  sessionId,
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
  loading: boolean;
  onClear: () => void;
  onClose: () => void;
  onExportImage: (blob: Blob) => Promise<void>;
  onRefresh: () => void;
  onReplayVoice: (voiceId: string) => void;
  onRevert: (userIndex: number) => void;
  onSaveVoice: (voiceId: string) => void;
  onToggleVoiceArchive: (enabled: boolean) => void;
  open: boolean;
  sessionId?: string;
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
  const [vnExportSnapshot, setVnExportSnapshot] = useState<VnExportSelectionSnapshot | null>(null);
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
    setVnExportSnapshot(null);
    setMulti(false);
    selection.reset();
    onClose();
  };
  useEffect(() => {
    if (!open) {
      setVnExportSnapshot(null);
    }
  }, [open]);
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
      const slice = snapshot.entries.slice(start, end + 1);
      const expected = historyRows.slice(first.originalIndex, last.originalIndex + 1);
      if (
        start < 0 ||
        end < start ||
        slice.length !== expected.length ||
        slice.some((item, index) => !sameHistoryMessage(expected[index].entry, item))
      ) {
        throw new Error(t("chat.replay.changed"));
      }
      setClip({
        mode,
        snapshot,
        entries: slice,
        includesUnselected: slice.some((item) => !selection.selected.has(item.id)),
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
  const playableSelectedRows = selectedRows.filter(({ entry }) => entry.role !== "options");
  const openVnExport = () => {
    if (!playableSelectedRows.length) return;
    setVnExportSnapshot({
      expectedSessionId: sessionId,
      selectedEntryIds: playableSelectedRows.map(({ entry }) => entry.id),
      selectedEntryAnchors: playableSelectedRows.map(({ entry }) => ({
        id: entry.id,
        role: entry.role,
        dialogId: entry.dialogId ?? "",
        text: entry.text,
      })),
      startEntryId: playableSelectedRows[0]?.entry.id,
      endEntryId: playableSelectedRows.at(-1)?.entry.id,
      rangeCount: playableSelectedRows.length,
    });
  };
  const visibleEntries = useMemo(
    () =>
      historyRows.filter(({ dialog, entry }) =>
        `${dialog.speaker} ${dialog.body} ${roleLabels[entry.role]}`.toLocaleLowerCase().includes(normalizedQuery),
      ),
    [historyRows, normalizedQuery, roleLabels],
  );
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
    <>
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
        open={open && !vnExportSnapshot}
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
              {renderedEntries.map(({ dialog, entry, localTime, originalIndex }) => (
                <HistoryEntryCard
                  anchored={multi && selection.anchor === entry.id}
                  checked={selection.selected.has(entry.id)}
                  dialog={dialog}
                  disabled={preparing || Boolean(clip)}
                  entry={entry}
                  key={entry.id}
                  localTime={localTime}
                  multi={multi}
                  onReplayVoice={onReplayVoice}
                  onRevert={onRevert}
                  onSaveVoice={onSaveVoice}
                  onSelect={
                    multi && !clip && !preparing
                      ? (event, entryId) => {
                          if (feedback) setFeedback(undefined);
                          selection.click(event, entryId);
                        }
                      : undefined
                  }
                  originalIndex={originalIndex}
                  roleLabel={roleLabels[entry.role]}
                />
              ))}
            </div>
          ) : null}
        </div>
        {multi ? (
          <HistorySelectionFooter
            clip={clip}
            feedback={feedback}
            generate={generate}
            generatable={generatable}
            hasAnchor={Boolean(selection.anchor)}
            hasReplayHandler={Boolean(onStartReplay)}
            onBegin={() => void begin()}
            onClearClip={clearClip}
            onCopy={() => void exportSelection(false)}
            onOpenVnExport={openVnExport}
            onPrepare={(mode) => void prepare(mode)}
            onScreenshot={() => void exportSelection(true)}
            onSelectAll={() => selection.reset(visibleEntries.map(({ entry }) => entry.id))}
            onSelectToEnd={selection.selectToVisibleEnd}
            onToggleGenerate={setGenerate}
            playableSelectedCount={playableSelectedRows.length}
            preparing={preparing}
            replayDisabled={replayDisabled}
            selectedCount={selectedRows.length}
            videoAvailable={videoAvailable}
            visibleCount={visibleEntries.length}
          />
        ) : (
          <footer className="chat-stage-modal__footer chat-history-dialog__footer">
            <Button onClick={onRefresh}>{t("common.refresh")}</Button>
            <Button onClick={close}>{t("common.close")}</Button>
          </footer>
        )}
      </ChatStageModal>
      <VnExportDialog
        defaultUserDisplayName={userDisplayName}
        endEntryId={vnExportSnapshot?.endEntryId}
        expectedSessionId={vnExportSnapshot?.expectedSessionId}
        onClose={() => setVnExportSnapshot(null)}
        open={open && Boolean(vnExportSnapshot)}
        rangeCount={vnExportSnapshot?.rangeCount}
        selectedEntryAnchors={vnExportSnapshot?.selectedEntryAnchors}
        selectedEntryIds={vnExportSnapshot?.selectedEntryIds}
        startEntryId={vnExportSnapshot?.startEntryId}
      />
    </>
  );
}
