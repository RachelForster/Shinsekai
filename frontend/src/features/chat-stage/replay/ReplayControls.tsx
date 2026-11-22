import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import {
  History,
  ChevronUp,
  CircleAlert,
  LocateFixed,
  MessageCircle,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
  Square,
  VolumeX,
} from "lucide-react";
import { cancelChatReplay, controlChatReplay } from "../../../entities/chat/repository";
import type { ChatReplayControl, ChatReplayProgress, ChatReplaySnapshot } from "../../../shared/platform/types";
import { useI18n } from "../../../shared/i18n";
import { Button, IconButton } from "../../../shared/ui";
import { ChatStageModal } from "../components/ChatStageModal";
import type { ReplayCapture } from "./historyExport";
import "./replay.css";

export interface ActiveReplay {
  snapshot: ChatReplaySnapshot;
  generate: boolean;
  capture?: ReplayCapture;
}

export function ReplayControls({
  replay,
  progress,
  onExit,
}: {
  replay: ActiveReplay;
  progress?: ChatReplayProgress | null;
  onExit: (toHistory: boolean) => void;
}) {
  const { t } = useI18n();
  const [locating, setLocating] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const panelId = useId();
  const expanded = hovered || keyboardOpen || pinned;
  const [scrubIndex, setScrubIndex] = useState<number>();
  const scrubbing = useRef(false);
  const cancelTimer = useRef<number>();
  const playerRef = useRef<HTMLDivElement>(null);
  const current = progress?.id === replay.snapshot.id ? progress : null;
  const index = current?.index ?? 0;
  const paused = current?.paused ?? false;
  const ended = current?.ended ?? false;
  const total = replay.snapshot.entries.length;
  const position = scrubIndex ?? index;
  const progressText = t("chat.replay.progress", { current: position + 1, total });
  const progressPercent = total > 1 ? (position / (total - 1)) * 100 : ended ? 100 : 0;

  useLayoutEffect(() => {
    const player = playerRef.current;
    const stage = player?.closest<HTMLElement>(".chat-stage");
    const input = stage?.querySelector<HTMLElement>(".input-layer");
    if (!player || !stage || !input) return;
    const measure = () => {
      stage.style.setProperty(
        "--chat-replay-input-top",
        `${stage.getBoundingClientRect().bottom - input.getBoundingClientRect().top}px`,
      );
      stage.style.setProperty("--chat-replay-player-height", `${player.getBoundingClientRect().height}px`);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(player);
    observer.observe(input);
    observer.observe(stage);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      stage.style.removeProperty("--chat-replay-input-top");
      stage.style.removeProperty("--chat-replay-player-height");
    };
  }, []);
  const control = useCallback(
    async (value: ChatReplayControl) => {
      try {
        setError("");
        await controlChatReplay(replay.snapshot.id, value);
      } catch (cause) {
        setError(String(cause));
      }
    },
    [replay.snapshot.id],
  );
  const exit = useCallback(
    async (toHistory: boolean) => {
      setBusy(true);
      try {
        // End recording before the live stage is restored by cancellation.
        replay.capture?.stop(true);
        await cancelChatReplay(replay.snapshot.id);
        onExit(toHistory);
      } catch (cause) {
        setError(String(cause));
      } finally {
        setBusy(false);
      }
    },
    [onExit, replay.capture, replay.snapshot.id],
  );
  const togglePlayback = useCallback(
    () => void control(ended ? { action: "seek", index: 0, playing: true } : { action: paused ? "play" : "pause" }),
    [control, ended, paused],
  );

  useEffect(() => {
    window.clearTimeout(cancelTimer.current);
    return () => {
      cancelTimer.current = window.setTimeout(() => {
        void cancelChatReplay(replay.snapshot.id).catch(() => {});
      }, 0);
    };
  }, [replay.snapshot.id]);

  useEffect(() => {
    if (locating) return;
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        void exit(true);
        return;
      }
      if ((event.target as HTMLElement)?.closest("a,button,input,textarea,select,[contenteditable=true]")) return;
      if (event.key === " ") togglePlayback();
      else if (event.key === "ArrowLeft") void control({ action: "seek", index: Math.max(0, index - 1) });
      else if (event.key === "ArrowRight")
        void control({ action: "seek", index: Math.min(replay.snapshot.entries.length - 1, index + 1) });
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [locating, control, exit, index, togglePlayback, total]);

  const seekFromTimeline = (target: number) => {
    if (target !== index) void control({ action: "seek", index: target, playing: !paused && !ended });
  };

  return (
    <>
      <div
        ref={playerRef}
        className="chat-replay-player"
        data-chat-stage-hitbox="true"
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
        onPointerEnter={(event) => {
          if (event.pointerType === "mouse") setHovered(true);
        }}
        onPointerLeave={() => setHovered(false)}
        onFocusCapture={(event) => {
          if (event.target.matches(":focus-visible")) setKeyboardOpen(true);
        }}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) {
            setKeyboardOpen(false);
            setPinned(false);
          }
        }}
      >
        <IconButton
          className="chat-replay-handle"
          label={t("chat.replay.showControls")}
          aria-controls={panelId}
          aria-expanded={expanded}
          onClick={() => {
            if (!hovered) setPinned((value) => !value);
          }}
        >
          <ChevronUp aria-hidden />
        </IconButton>
        <div
          className="chat-replay-controls"
          id={panelId}
          role="group"
          aria-label={t("chat.replay.title")}
          hidden={!expanded}
        >
          <div className="chat-replay-meta">
            <span className="visually-hidden" role="status">
              {t(ended ? "chat.replay.ended" : paused ? "chat.replay.paused" : "chat.replay.title")}
              {(current?.waiting || current?.error) &&
                t(current.error ? "chat.replay.voiceFailed" : "chat.replay.waiting")}
            </span>
            <span className="chat-replay-position" title={progressText}>
              {position + 1}/{total}
            </span>
          </div>
          <input
            className="chat-replay-timeline"
            type="range"
            min={0}
            max={Math.max(0, total - 1)}
            value={position}
            aria-label={t("chat.replay.timeline")}
            aria-valuetext={progressText}
            disabled={busy || total < 2}
            style={{ "--replay-progress": `${progressPercent}%` } as CSSProperties}
            onPointerDown={() => {
              scrubbing.current = true;
            }}
            onChange={(event) => {
              const target = event.currentTarget.valueAsNumber;
              if (scrubbing.current) setScrubIndex(target);
              else seekFromTimeline(target);
            }}
            onPointerUp={(event) => {
              scrubbing.current = false;
              setScrubIndex(undefined);
              seekFromTimeline(event.currentTarget.valueAsNumber);
            }}
            onPointerCancel={() => {
              scrubbing.current = false;
              setScrubIndex(undefined);
            }}
          />
          <div className="chat-replay-transport">
            <div className="chat-replay-primary">
              <IconButton
                className="chat-replay-icon"
                label={t("chat.replay.previous")}
                disabled={busy || index === 0}
                onClick={() => void control({ action: "seek", index: index - 1 })}
              >
                <SkipBack aria-hidden />
              </IconButton>
              <IconButton
                className="chat-replay-icon chat-replay-icon--play"
                label={t(ended ? "chat.replay.restart" : paused ? "chat.replay.play" : "chat.replay.pause")}
                disabled={busy}
                onClick={togglePlayback}
              >
                {ended ? <RotateCcw aria-hidden /> : paused ? <Play aria-hidden /> : <Pause aria-hidden />}
              </IconButton>
              <IconButton
                className="chat-replay-icon"
                label={t("chat.replay.next")}
                disabled={busy || index >= total - 1}
                onClick={() => void control({ action: "seek", index: index + 1 })}
              >
                <SkipForward aria-hidden />
              </IconButton>
            </div>
            <div className="chat-replay-secondary">
              {ended ? (
                <>
                  <IconButton
                    className="chat-replay-icon"
                    label={t("chat.replay.history")}
                    disabled={busy}
                    onClick={() => void exit(true)}
                  >
                    <History aria-hidden />
                  </IconButton>
                  <IconButton
                    className="chat-replay-icon"
                    label={t("chat.replay.chat")}
                    disabled={busy}
                    onClick={() => void exit(false)}
                  >
                    <MessageCircle aria-hidden />
                  </IconButton>
                </>
              ) : (
                <>
                  <IconButton
                    className="chat-replay-icon"
                    label={t("chat.replay.locate")}
                    disabled={busy}
                    onClick={() => {
                      void control({ action: "pause" });
                      setLocating(true);
                    }}
                  >
                    <LocateFixed aria-hidden />
                  </IconButton>
                  <IconButton
                    className="chat-replay-icon"
                    label={t("chat.replay.exit")}
                    disabled={busy}
                    onClick={() => void exit(true)}
                  >
                    <Square aria-hidden />
                  </IconButton>
                </>
              )}
            </div>
          </div>
          {(current?.waiting || current?.error || error) && (
            <div className="chat-replay-notice">
              {current?.error && (
                <IconButton
                  className="chat-replay-icon"
                  label={t("chat.replay.retry")}
                  disabled={busy}
                  onClick={() => void control({ action: "retry" })}
                >
                  <RotateCcw aria-hidden />
                </IconButton>
              )}
              {(current?.waiting || current?.error) && (
                <IconButton
                  className="chat-replay-icon"
                  label={t("chat.replay.skipVoice")}
                  disabled={busy}
                  onClick={() => void control({ action: "skip-voice" })}
                >
                  <VolumeX aria-hidden />
                </IconButton>
              )}
              {error && (
                <span role="alert" className="chat-replay-alert" title={error}>
                  <CircleAlert aria-hidden />
                  <span className="visually-hidden">{error}</span>
                </span>
              )}
            </div>
          )}
        </div>
      </div>
      {createPortal(
        <ChatStageModal
          open={locating}
          onClose={() => setLocating(false)}
          title={t("chat.replay.locate")}
          closeLabel={t("common.close")}
          labelledBy="replay-locate-title"
          dialogClassName="chat-history-dialog"
          backdropClassName="chat-history-backdrop"
        >
          <div className="chat-stage-modal__body">
            <input
              className="chat-history__search"
              aria-label={t("chat.history.search")}
              placeholder={t("chat.history.search")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            {replay.snapshot.entries.map(
              (item, position) =>
                item.text.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) && (
                  <section className="chat-history__entry" key={item.key} data-replay-current={position === index}>
                    <p>
                      {item.position}. {item.text}
                    </p>
                    <Button
                      onClick={() => {
                        void control({ action: "seek", index: position });
                        setLocating(false);
                      }}
                    >
                      {t("chat.replay.jump")}
                    </Button>
                  </section>
                ),
            )}
          </div>
        </ChatStageModal>,
        document.querySelector(".chat-stage") ?? document.body,
      )}
    </>
  );
}
