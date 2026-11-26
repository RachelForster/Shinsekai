import { useEffect, useRef, useState, type AnimationEvent, type CSSProperties, type ReactNode } from "react";

import type { ChatStageSpriteMotion } from "../state/types";

export function SpriteMotionBox({ children, motion }: { children: ReactNode; motion?: ChatStageSpriteMotion | null }) {
  const [activeMotion, setActiveMotion] = useState<string>("");
  const lastSeqRef = useRef<number>(0);

  useEffect(() => {
    const seq = motion?.seq ?? 0;
    const motionName = motion?.motion?.trim() ?? "";
    if (!motionName || seq <= 0) {
      lastSeqRef.current = 0;
      setActiveMotion("");
      return;
    }
    if (seq === lastSeqRef.current) {
      return;
    }
    lastSeqRef.current = seq;
    setActiveMotion("");

    let cancelled = false;
    let rafId = 0;
    let clearTimer = 0;
    const durationMs = Math.max(200, motion?.durationMs ?? 600);

    const activate = () => {
      if (cancelled) {
        return;
      }
      setActiveMotion(motionName);
      clearTimer = window.setTimeout(() => {
        if (!cancelled) {
          setActiveMotion("");
        }
      }, durationMs + 120);
    };

    if (typeof window.requestAnimationFrame === "function") {
      rafId = window.requestAnimationFrame(activate);
    } else {
      clearTimer = window.setTimeout(activate, 0);
    }

    return () => {
      cancelled = true;
      if (rafId && typeof window.cancelAnimationFrame === "function") {
        window.cancelAnimationFrame(rafId);
      }
      if (clearTimer) {
        window.clearTimeout(clearTimer);
      }
    };
  }, [motion?.durationMs, motion?.motion, motion?.seq]);

  const handleAnimationEnd = (event: AnimationEvent<HTMLDivElement>) => {
    // Ignore bubbling animation events from child sprite visuals (e.g. entrance transitions).
    if (event.target === event.currentTarget) {
      setActiveMotion("");
    }
  };

  const style: CSSProperties | undefined = activeMotion
    ? ({ "--sprite-motion-duration": `${Math.max(200, motion?.durationMs ?? 600)}ms` } as CSSProperties)
    : undefined;

  return (
    <div
      className="sprite-motion-box"
      data-motion={activeMotion || undefined}
      onAnimationEnd={handleAnimationEnd}
      style={style}
    >
      {children}
    </div>
  );
}
