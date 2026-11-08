import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { LocateFixed, Pause, Play, SkipBack, SkipForward, Square } from "lucide-react";
import { cancelChatReplay, controlChatReplay } from "../../../entities/chat/repository";
import type { ChatReplayControl, ChatReplayProgress, ChatReplaySnapshot } from "../../../shared/platform/types";
import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { ChatStageModal } from "../components/ChatStageModal";
import "./replay.css";

export interface ActiveReplay {
  snapshot: ChatReplaySnapshot;
  generate: boolean;
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
  const cancelTimer = useRef<number>();
  const controlsRef = useRef<HTMLDivElement>(null);
  const current = progress?.id === replay.snapshot.id ? progress : null;
  const index = current?.index ?? 0;
  const paused = current?.paused ?? false;
  const ended = current?.ended ?? false;
  const entry = replay.snapshot.entries[index];

  useLayoutEffect(() => {
    const controls = controlsRef.current;
    const stage = controls?.closest<HTMLElement>(".chat-stage");
    if (!controls || !stage) return;
    const measure = () => {
      stage.style.setProperty(
        "--chat-replay-dialog-bottom",
        `${Math.max(0, stage.getBoundingClientRect().bottom - controls.getBoundingClientRect().top + 16)}px`,
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(controls);
    observer.observe(stage);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      stage.style.removeProperty("--chat-replay-dialog-bottom");
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
        await cancelChatReplay(replay.snapshot.id);
        onExit(toHistory);
      } catch (cause) {
        setError(String(cause));
      } finally {
        setBusy(false);
      }
    },
    [onExit, replay.snapshot.id],
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
      if (event.key === " ") void control({ action: paused ? "play" : "pause" });
      else if (event.key === "ArrowLeft") void control({ action: "seek", index: Math.max(0, index - 1) });
      else if (event.key === "ArrowRight")
        void control({ action: "seek", index: Math.min(replay.snapshot.entries.length - 1, index + 1) });
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [locating, control, exit, index, paused, replay.snapshot.entries.length]);

  return (
    <>
      <div
        ref={controlsRef}
        className="chat-replay-controls"
        aria-label={t("chat.replay.title")}
        data-chat-stage-hitbox="true"
      >
        <div className="chat-replay-notice" aria-live="polite">
          <strong>{t(ended ? "chat.replay.ended" : "chat.replay.title")}</strong>
          <span>{t("chat.replay.progress", { current: index + 1, total: replay.snapshot.entries.length })}</span>
          {(current?.voiceSource ?? entry?.voiceSource) === "generated" && <span>{t("chat.replay.generated")}</span>}
          {(current?.voiceLabel ?? entry?.voiceLabel) && <span>{current?.voiceLabel ?? entry?.voiceLabel}</span>}
          {current?.waiting && <span>{t(current.error ? "chat.replay.voiceFailed" : "chat.replay.waiting")}</span>}
          {current?.error && (
            <Button onClick={() => void control({ action: "retry" })}>{t("chat.replay.retry")}</Button>
          )}
          {(current?.waiting || current?.error) && (
            <Button onClick={() => void control({ action: "skip-voice" })}>{t("chat.replay.skipVoice")}</Button>
          )}
          {error && <span role="alert">{error}</span>}
        </div>
        <div className="chat-replay-buttons">
          {ended ? (
            <>
              <Button
                onClick={() => void control({ action: "seek", index: 0, playing: true })}
                icon={<Play aria-hidden className="button__icon" />}
              >
                {t("chat.replay.restart")}
              </Button>
              <Button disabled={busy} onClick={() => void exit(true)}>
                {t("chat.replay.history")}
              </Button>
              <Button disabled={busy} onClick={() => void exit(false)} variant="primary">
                {t("chat.replay.chat")}
              </Button>
            </>
          ) : (
            <>
              <Button
                disabled={index === 0}
                onClick={() => void control({ action: "seek", index: index - 1 })}
                icon={<SkipBack aria-hidden className="button__icon" />}
              >
                {t("chat.replay.previous")}
              </Button>
              <Button
                onClick={() => void control({ action: paused ? "play" : "pause" })}
                variant="primary"
                icon={
                  paused ? (
                    <Play aria-hidden className="button__icon" />
                  ) : (
                    <Pause aria-hidden className="button__icon" />
                  )
                }
              >
                {t(paused ? "chat.replay.play" : "chat.replay.pause")}
              </Button>
              <Button
                disabled={index === replay.snapshot.entries.length - 1}
                onClick={() => void control({ action: "seek", index: index + 1 })}
                icon={<SkipForward aria-hidden className="button__icon" />}
              >
                {t("chat.replay.next")}
              </Button>
              <Button
                onClick={() => {
                  void control({ action: "pause" });
                  setLocating(true);
                }}
                icon={<LocateFixed aria-hidden className="button__icon" />}
              >
                {t("chat.replay.locate")}
              </Button>
              <Button
                disabled={busy}
                onClick={() => void exit(true)}
                icon={<Square aria-hidden className="button__icon" />}
              >
                {t("chat.replay.exit")}
              </Button>
            </>
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
