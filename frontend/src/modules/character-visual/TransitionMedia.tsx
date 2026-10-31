import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { VisualMedia, type VisualMediaProps } from "../../shared/ui/VisualMedia";
import {
  SPRITE_TRANSITION_PLAYBACK_RATE,
  SPRITE_TRANSITION_FRAME_COUNT,
  SPRITE_TRANSITION_FPS,
} from "../../shared/assets/spriteTransition";

interface Playback {
  id: number;
  to: string;
  url: string;
  phase: "loading" | "playing" | "waiting" | "fallback";
  duration: number;
}

/** Keep each surface mounted through both handoffs; never discard the preloaded target. */
export function TransitionMedia({
  transitions,
  enabled,
  ...props
}: VisualMediaProps & {
  transitions?: { fromUrl: string; url: string }[];
  enabled: boolean;
}) {
  const [displayed, setDisplayed] = useState(props.src);
  const settled = useRef(props.src);
  const target = useRef(props.src);
  const sequence = useRef(0);
  const [clip, setClip] = useState<Playback | null>(null);
  const playback = useRef(clip);
  playback.current = clip;
  const ready = useRef(new Set<string>());
  const dimensions = useRef(new Map<string, [number, number]>());
  const [aspectRatio, setAspectRatio] = useState(1);
  const [reduced, setReduced] = useState(
    () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
  );
  const incoming = useRef(transitions);
  incoming.current = transitions;
  const commit = (src: string) => {
    settled.current = src;
    playback.current = null;
    setDisplayed(src);
    setClip(null);
    const size = dimensions.current.get(src);
    if (size) {
      setAspectRatio(size[0] / size[1]);
      props.onDimensions?.(...size);
    }
  };
  const isCurrent = (edge: Playback) => playback.current?.id === edge.id && target.current === edge.to;
  const finish = (edge: Playback, failed = false) => {
    if (!isCurrent(edge)) return;
    if (ready.current.has(edge.to)) commit(edge.to);
    else
      setClip((current) =>
        current?.id === edge.id ? { ...current, phase: failed ? "fallback" : "waiting" } : current,
      );
  };
  const rememberDimensions = (src: string, width: number, height: number) => {
    if (width <= 0 || height <= 0) return;
    dimensions.current.set(src, [width, height]);
    // H3 rounds its canvas dimensions. Use enough width for every surface so
    // contain does not shrink the bridge's height between two full-height sprites.
    const sources = playback.current ? [settled.current, target.current, playback.current.url] : [settled.current];
    const sizes = sources.flatMap((source) => {
      const size = dimensions.current.get(source);
      return size ? [size] : [];
    });
    const size = sizes.reduce<[number, number] | undefined>(
      (widest, next) => (!widest || next[0] / next[1] > widest[0] / widest[1] ? next : widest),
      undefined,
    );
    if (size) {
      setAspectRatio(size[0] / size[1]);
      props.onDimensions?.(...size);
    }
  };

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const change = () => setReduced(Boolean(media?.matches));
    media?.addEventListener("change", change);
    return () => media?.removeEventListener("change", change);
  }, []);

  useLayoutEffect(() => {
    const changed = target.current !== props.src;
    target.current = props.src;
    if (!enabled || props.active === false || reduced || document.visibilityState === "hidden") {
      commit(props.src);
      return;
    }
    if (!changed) return;
    const edge = incoming.current?.find((edge) => edge.fromUrl === settled.current);
    if (edge && settled.current !== props.src) {
      setClip({
        id: ++sequence.current,
        to: props.src,
        url: edge.url,
        phase: "loading",
        duration: SPRITE_TRANSITION_FRAME_COUNT / SPRITE_TRANSITION_FPS,
      });
    } else commit(props.src);
  }, [props.src, props.active, enabled, reduced]);

  useEffect(() => {
    const retained = new Set([displayed, props.src, clip?.url]);
    for (const src of ready.current) if (!retained.has(src)) ready.current.delete(src);
    for (const src of dimensions.current.keys()) if (!retained.has(src)) dimensions.current.delete(src);
  }, [displayed, props.src, clip?.url]);

  useEffect(() => {
    if (!clip) return;
    const waiting = clip.phase === "waiting" || clip.phase === "fallback";
    const timeout = clip.phase === "playing" ? (clip.duration / SPRITE_TRANSITION_PLAYBACK_RATE) * 1000 + 1000 : 2000;
    const timer = window.setTimeout(() => {
      if (!isCurrent(clip)) return;
      if (waiting) commit(clip.to);
      else finish(clip, true);
    }, timeout);
    const hidden = () => {
      if (document.visibilityState === "hidden" && isCurrent(clip)) commit(clip.to);
    };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [clip]);

  const showClip = clip?.phase === "playing" || clip?.phase === "waiting";
  return (
    <div
      className={`${props.className ?? ""} character-visual__transition`}
      style={{ aspectRatio, ...props.style }}
      data-chat-stage-hitbox={props.hitbox ? "true" : undefined}
      onMouseDown={props.onMouseDown}
    >
      {[...new Set([displayed, props.src])].map((src) => {
        const visible = src === displayed && !showClip;
        return (
          <div
            key={src}
            className="character-visual__transition-layer"
            style={{ opacity: visible ? 1 : 0 }}
            aria-hidden={!visible}
          >
            <VisualMedia
              {...props}
              src={src}
              alt={src === props.src ? props.alt : ""}
              className="character-visual__static-image"
              style={undefined}
              active={props.active !== false && src === displayed && !clip}
              autoPlay={src === displayed && !clip ? props.autoPlay : false}
              preload="auto"
              hitbox={false}
              onMouseDown={undefined}
              onDimensions={(width, height) => {
                rememberDimensions(src, width, height);
              }}
              onFrameReady={(element) => {
                ready.current.add(src);
                props.onFrameReady?.(element);
                const current = playback.current;
                if (current?.to === src && (current.phase === "waiting" || current.phase === "fallback"))
                  finish(current);
              }}
              onError={(event) => {
                if (src !== target.current) return;
                commit(src);
                props.onError?.(event);
              }}
            />
          </div>
        );
      })}
      {clip ? (
        <VisualMedia
          key={clip.id}
          src={clip.url}
          alt=""
          loop={false}
          preload="auto"
          playbackRate={SPRITE_TRANSITION_PLAYBACK_RATE}
          active={props.active !== false && clip.phase !== "fallback"}
          className="character-visual__transition-layer"
          style={{ opacity: showClip ? 1 : 0 }}
          onDimensions={(width, height) => rememberDimensions(clip.url, width, height)}
          onFrameReady={(element) => {
            if (!isCurrent(clip) || playback.current?.phase !== "loading") return;
            const duration = element instanceof HTMLVideoElement ? element.duration : 0;
            setClip((current) =>
              current?.id === clip.id
                ? {
                    ...current,
                    phase: "playing",
                    duration: Number.isFinite(duration) && duration > 0 ? duration : current.duration,
                  }
                : current,
            );
          }}
          onEnded={() => finish(clip)}
          onPlayBlocked={() => finish(clip, true)}
          onError={() => finish(clip, true)}
        />
      ) : null}
    </div>
  );
}
