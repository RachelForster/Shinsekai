import { useEffect, useMemo, useState } from "react";
import type { ChatReplayProgress } from "../../../shared/platform/types";

export function useReplayDraft(replay?: ChatReplayProgress | null) {
  const input = replay?.input;
  const typing = input?.phase === "typing";
  const text = typing ? input.text : "";
  const duration = typing ? input.durationMs : 0;
  const key = typing ? `${replay?.id}:${input.epoch}:${replay?.index}` : "";
  const characters = useMemo(
    () =>
      typeof Intl.Segmenter === "function"
        ? Array.from(new Intl.Segmenter().segment(text), (part) => part.segment)
        : Array.from(text),
    [text],
  );
  const [clock, setClock] = useState({ key: "", elapsed: 0 });
  const elapsed = clock.key === key ? clock.elapsed : 0;
  const paused = Boolean(replay?.paused);

  useEffect(() => {
    if (!key || paused || duration <= 0) return;
    let last = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const delta = now - last;
      last = now;
      setClock((current) => {
        const elapsed = Math.min(duration, (current.key === key ? current.elapsed : 0) + delta);
        return current.key === key && elapsed === current.elapsed ? current : { key, elapsed };
      });
    }, 32);
    return () => window.clearInterval(timer);
  }, [key, paused, duration]);

  if (!typing || duration <= 0) return text;
  return characters.slice(0, Math.floor((elapsed / duration) * characters.length)).join("");
}
