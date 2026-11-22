import { useEffect, useRef, useState } from "react";

import { hideBrokenStageAsset, stageAssetUrl } from "../chatStageUtils";
import type { ChatStageAmbientEffect } from "../state/types";

const AMBIENT_FADE_MS = 500;

interface RenderedAmbientEffect {
  effect: ChatStageAmbientEffect;
  leaving: boolean;
}

export function AmbientLayer({
  effects,
  hidden,
  layer,
}: {
  effects: ChatStageAmbientEffect[];
  hidden: boolean;
  layer: "back" | "front";
}) {
  const visible = (hidden ? [] : effects).filter((effect) => effect.url && effect.layer === layer);
  const [rendered, setRendered] = useState<RenderedAmbientEffect[]>(() =>
    visible.map((effect) => ({ effect, leaving: false })),
  );
  const leaveTimersRef = useRef(new Map<string, number>());

  useEffect(() => {
    const desiredByKey = new Map(visible.map((effect) => [effect.key, effect]));
    setRendered((current) => {
      const next = current.map((item) => {
        const replacement = desiredByKey.get(item.effect.key);
        if (replacement) {
          return { effect: replacement, leaving: false };
        }
        return item.leaving ? item : { ...item, leaving: true };
      });
      const renderedKeys = new Set(next.map((item) => item.effect.key));
      for (const effect of visible) {
        if (!renderedKeys.has(effect.key)) {
          next.push({ effect, leaving: false });
        }
      }
      return next;
    });
  }, [effects, hidden, layer]);

  useEffect(() => {
    const timers = leaveTimersRef.current;
    for (const item of rendered) {
      if (!item.leaving || timers.has(item.effect.key)) {
        continue;
      }
      const key = item.effect.key;
      timers.set(
        key,
        window.setTimeout(() => {
          timers.delete(key);
          setRendered((current) => current.filter((entry) => !(entry.effect.key === key && entry.leaving)));
        }, AMBIENT_FADE_MS),
      );
    }
    for (const [key, timer] of timers) {
      if (!rendered.some((item) => item.effect.key === key && item.leaving)) {
        window.clearTimeout(timer);
        timers.delete(key);
      }
    }
  }, [rendered]);

  useEffect(
    () => () => {
      for (const timer of leaveTimersRef.current.values()) {
        window.clearTimeout(timer);
      }
      leaveTimersRef.current.clear();
    },
    [],
  );

  if (!rendered.length) {
    return null;
  }
  return (
    <div aria-hidden className="ambient-layer" data-layer={layer}>
      {rendered.map(({ effect, leaving }) => {
        const src = stageAssetUrl(effect.url);
        const mediaState = leaving ? "leaving" : "visible";
        if (/\.(?:m4v|mov|mp4|webm)(?:[?#]|$)/i.test(effect.url)) {
          return (
            <video
              autoPlay
              className="ambient-layer__media"
              data-state={mediaState}
              key={effect.key}
              loop
              muted
              onError={hideBrokenStageAsset}
              playsInline
              src={src}
            />
          );
        }
        return (
          <img
            alt=""
            className="ambient-layer__media"
            data-state={mediaState}
            key={effect.key}
            onError={hideBrokenStageAsset}
            src={src}
          />
        );
      })}
    </div>
  );
}
