import { ArrowDownToLine, BookOpen, Camera, Clapperboard, Copy, Video } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { ChatReplaySnapshot } from "../../../shared/platform/types";
import { Button } from "../../../shared/ui";

export interface HistoryClip {
  mode: "replay" | "video";
  snapshot: ChatReplaySnapshot;
  entries: ChatReplaySnapshot["entries"];
  includesUnselected: boolean;
}

interface HistorySelectionFooterProps {
  clip: HistoryClip | null;
  feedback?: { text: string; error?: boolean };
  generate: boolean;
  generatable?: boolean;
  hasAnchor: boolean;
  hasReplayHandler: boolean;
  onBegin: () => void;
  onClearClip: () => void;
  onCopy: () => void;
  onOpenVnExport: () => void;
  onPrepare: (mode: HistoryClip["mode"]) => void;
  onScreenshot: () => void;
  onSelectAll: () => void;
  onSelectToEnd: () => void;
  onToggleGenerate: (checked: boolean) => void;
  playableSelectedCount: number;
  preparing: boolean;
  replayDisabled: boolean;
  selectedCount: number;
  videoAvailable: boolean;
  visibleCount: number;
}

export function HistorySelectionFooter({
  clip,
  feedback,
  generate,
  generatable,
  hasAnchor,
  hasReplayHandler,
  onBegin,
  onClearClip,
  onCopy,
  onOpenVnExport,
  onPrepare,
  onScreenshot,
  onSelectAll,
  onSelectToEnd,
  onToggleGenerate,
  playableSelectedCount,
  preparing,
  replayDisabled,
  selectedCount,
  videoAvailable,
  visibleCount,
}: HistorySelectionFooterProps) {
  const { t } = useI18n();

  return (
    <footer className="chat-history-selection">
      {!clip && hasAnchor && !preparing && (
        <Button
          className="chat-history-selection__to-end"
          icon={<ArrowDownToLine aria-hidden className="button__icon" />}
          onClick={onSelectToEnd}
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
                  onChange={(event) => onToggleGenerate(event.target.checked)}
                  type="checkbox"
                />
                {t("chat.history.selection.fillVoice")}
              </label>
            )}
            <Button onClick={onClearClip}>{t("chat.history.selection.edit")}</Button>
            <Button
              className="chat-history-selection__primary"
              disabled={preparing || replayDisabled}
              onClick={onBegin}
            >
              {t(clip.mode === "video" ? "chat.history.selection.record" : "chat.replay.direct")}
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className="chat-history-selection__summary">
            <strong role="status">{t("chat.history.selection.count", { count: selectedCount })}</strong>
            {selectedCount === 0 && <span>{t("chat.history.selection.hint")}</span>}
            {selectedCount > 0 && replayDisabled && hasReplayHandler && <span>{t("chat.replay.busy")}</span>}
          </div>
          <div className="chat-history-selection__actions">
            <Button disabled={preparing || visibleCount === 0} onClick={onSelectAll}>
              {t("chat.history.selection.all")}
            </Button>
            {hasReplayHandler && (
              <Button
                className="chat-history-selection__primary"
                disabled={!selectedCount || preparing || replayDisabled}
                icon={<Clapperboard aria-hidden className="button__icon" />}
                onClick={() => onPrepare("replay")}
              >
                {t("chat.history.selection.replay")}
              </Button>
            )}
            <Button
              disabled={!selectedCount || preparing}
              icon={<Copy aria-hidden className="button__icon" />}
              onClick={onCopy}
            >
              {t("chat.actionBar.copy")}
            </Button>
            <Button
              disabled={!selectedCount || preparing}
              icon={<Camera aria-hidden className="button__icon" />}
              onClick={onScreenshot}
            >
              {t("chat.history.selection.screenshot")}
            </Button>
            <Button
              disabled={!playableSelectedCount || preparing}
              icon={<BookOpen aria-hidden className="button__icon" />}
              onClick={onOpenVnExport}
            >
              {t("chat.vnExport.button")}
            </Button>
            {hasReplayHandler && (
              <Button
                disabled={!selectedCount || preparing || replayDisabled || !videoAvailable}
                title={videoAvailable ? undefined : t("chat.history.selection.videoUnsupported")}
                icon={<Video aria-hidden className="button__icon" />}
                onClick={() => onPrepare("video")}
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
  );
}
