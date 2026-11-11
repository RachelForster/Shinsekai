import { useEffect, useRef, useState } from "react";

import { VisualMedia, type VisualMediaProps } from "../../shared/ui/VisualMedia";
import { bindAvatarVoice } from "./voiceRoute";
import type { SpriteTransitionPresentation } from "../../shared/assets/spriteTransition";
import { transitionAdjustment } from "./transitionPresentation";

/** A short silence pauses the same decoded video; only a voice boundary returns to idle. */
export function SpeakingMedia({
  speakingSrc,
  voiceCharacterName,
  speakingPresentation,
  ...props
}: VisualMediaProps & {
  speakingSrc: string;
  voiceCharacterName: string;
  speakingPresentation?: SpriteTransitionPresentation;
}) {
  const [speaking, setSpeaking] = useState(false);
  const [moving, setMoving] = useState(false);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [aspect, setAspect] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const video = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    setSpeaking(false);
    setMoving(false);
    let running = false;
    let started = false;
    let rate = 1;
    let lastLevelAt = performance.now() - 16;
    const pause = () => {
      running = false;
      setMoving(false);
      clearTimeout(timer.current);
      timer.current = undefined;
    };
    const unbind = bindAvatarVoice(voiceCharacterName, {
      notifySpeechEvent(event) {
        started = event === "started";
        setSpeaking(started);
        if (!started) pause();
        else {
          running = true;
          setMoving(true);
        }
      },
      setSpeechActivity(level) {
        if (!started) return;
        const activity = Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : 0;
        const now = performance.now();
        const elapsed = Math.max(0, Math.min(64, now - lastLevelAt));
        lastLevelAt = now;
        // A small, eased tempo change follows phrase accents without jerking the body.
        const targetRate = 0.92 + 0.16 * Math.sqrt(activity);
        rate += (targetRate - rate) * (1 - Math.exp(-elapsed / 160));
        if (video.current) video.current.playbackRate = rate;
        if (activity >= (running ? 0.015 : 0.04)) {
          clearTimeout(timer.current);
          timer.current = undefined;
          running = true;
          setMoving(true);
        } else if (running && timer.current === undefined) {
          // Ignore very short gaps between syllables instead of chattering on every sample.
          timer.current = setTimeout(pause, 140);
        }
      },
    });
    return () => {
      unbind();
      clearTimeout(timer.current);
      if (video.current) video.current.playbackRate = 1;
    };
  }, [voiceCharacterName]);

  const visible = props.active !== false && speaking && ready && !failed;
  // Use a constant correction over this loop: body motion must not pump the framing.
  const adjustment = transitionAdjustment(speakingPresentation, 0.5, aspect);
  return (
    <>
      <VisualMedia
        {...props}
        active={props.active !== false && !visible}
        style={{ ...props.style, opacity: visible ? 0 : 1, transition: "opacity 80ms linear" }}
      />
      <VisualMedia
        src={speakingSrc}
        alt=""
        className="character-visual__transition-layer"
        style={{
          opacity: visible ? 1 : 0,
          transition: "opacity 80ms linear",
          transform: `translate(${adjustment.x * 100}%, ${adjustment.y * 100}%) scale(${adjustment.scale})`,
          filter: `brightness(${adjustment.brightness})`,
        }}
        active={visible && moving}
        autoPlay
        loop
        preload="auto"
        onFrameReady={(element) => {
          video.current = element instanceof HTMLVideoElement ? element : null;
          const parent = element.parentElement;
          if (parent && parent.clientHeight > 0) setAspect(parent.clientWidth / parent.clientHeight);
          setReady(true);
        }}
        onError={() => setFailed(true)}
        onPlayBlocked={() => setFailed(true)}
      />
    </>
  );
}
