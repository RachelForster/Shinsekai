import { useEffect, useRef, useState, type MouseEventHandler } from "react";

import { VisualMedia } from "../../../shared/ui";
import { hideBrokenStageAsset, layerClassName, stageAssetUrl } from "../chatStageUtils";
import type { ChatStageBackgroundTransition } from "../state/types";

const TRANSITION_DURATIONS_MS: Record<string, number> = {
  fade: 550,
  fade_black: 850,
  fade_white: 850,
  slide_left: 550,
  slide_right: 550,
  zoom: 650,
};

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
}

export function BackgroundTransitionLayer({
  hidden,
  onDragStart,
  path,
  transition,
  transparent,
}: {
  hidden: boolean;
  onDragStart?: MouseEventHandler<HTMLElement>;
  path?: string;
  transition?: ChatStageBackgroundTransition | null;
  transparent: boolean;
}) {
  const nextSrc = stageAssetUrl(path);
  const [activeSrc, setActiveSrc] = useState(nextSrc);
  const [outgoingSrc, setOutgoingSrc] = useState("");
  const [activeTransition, setActiveTransition] = useState<string>("");
  const prevSrcRef = useRef(nextSrc);
  const lastSeqRef = useRef(0);

  useEffect(() => {
    const prevSrc = prevSrcRef.current;
    prevSrcRef.current = nextSrc;

    const seq = transition?.seq ?? 0;
    const rawEffect = (transition?.effect ?? "").trim().toLowerCase();
    const durationMs = TRANSITION_DURATIONS_MS[rawEffect] ?? 0;
    const hasSrcChange = nextSrc !== prevSrc;
    const hasNewCurtainPulse =
      !hasSrcChange && seq > lastSeqRef.current && (rawEffect === "fade_black" || rawEffect === "fade_white");
    if (seq > 0) {
      lastSeqRef.current = seq;
    }

    if (!nextSrc || (!hasSrcChange && !hasNewCurtainPulse)) {
      setActiveSrc(nextSrc);
      setOutgoingSrc("");
      setActiveTransition("");
      return;
    }

    if (
      durationMs <= 0 ||
      prefersReducedMotion() ||
      (hasSrcChange && !prevSrc && rawEffect !== "fade_black" && rawEffect !== "fade_white")
    ) {
      setActiveSrc(nextSrc);
      setOutgoingSrc("");
      setActiveTransition("");
      return;
    }

    setOutgoingSrc(hasSrcChange ? prevSrc : "");
    setActiveSrc(nextSrc);
    setActiveTransition(rawEffect);

    const timer = window.setTimeout(() => {
      setOutgoingSrc("");
      setActiveTransition("");
    }, durationMs);
    return () => window.clearTimeout(timer);
  }, [nextSrc, transition?.effect, transition?.seq]);

  const showCurtain = activeTransition === "fade_black" || activeTransition === "fade_white";

  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("chat-stage__background", hidden)}
      data-chat-stage-hitbox={onDragStart ? "true" : undefined}
      data-draggable={onDragStart ? "true" : "false"}
      data-transition={activeTransition || undefined}
      data-transparent={transparent ? "true" : "false"}
      hidden={hidden}
      onMouseDown={onDragStart}
    >
      {transparent ? null : <div aria-hidden className="chat-stage__fallback" />}
      {outgoingSrc ? (
        <div
          aria-hidden
          className="stage-bg-layer stage-bg-layer--outgoing"
          data-transition={activeTransition || undefined}
          key={`out:${outgoingSrc}`}
        >
          <VisualMedia active={!hidden} alt="" onError={hideBrokenStageAsset} src={outgoingSrc} />
        </div>
      ) : null}
      {activeSrc ? (
        <div
          className={activeTransition ? "stage-bg-layer stage-bg-layer--incoming" : "stage-bg-layer"}
          data-transition={activeTransition || undefined}
          key={`in:${activeSrc}`}
        >
          <VisualMedia active={!hidden} alt="" onError={hideBrokenStageAsset} src={activeSrc} />
        </div>
      ) : null}
      {showCurtain ? <div aria-hidden className="stage-bg-curtain" data-transition={activeTransition} /> : null}
    </div>
  );
}
