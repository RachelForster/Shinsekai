import { useCallback, useEffect, useRef, useState } from "react";

import { fileUrl } from "../../entities/files/repository";
import { getChatSnapshot, subscribeChat } from "../../entities/chat/repository";
import type { ReminderNotice } from "../../entities/reminder/types";
import { isReminderWindowVisible, onReminderWindowHidden } from "../../shared/desktop/remindersApi";

const keyOf = (notice: ReminderNotice) => `${notice.id}:${notice.due_at}`;
const playedStorage = "shinsekai.reminder.playedAudio";

function previouslyPlayed(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(playedStorage) ?? "[]"));
  } catch {
    return new Set();
  }
}

export function useReminderAudio(notices: ReminderNotice[]) {
  const [muted, setMuted] = useState(() => {
    try {
      return localStorage.getItem("shinsekai.reminder.muted") === "true";
    } catch {
      return false;
    }
  });
  const [playing, setPlaying] = useState("");
  const [speechDisabled, setSpeechDisabled] = useState(false);
  const speechDisabledRef = useRef(false);
  const sessionPolicyRef = useRef<boolean | null>(null);
  const policyVersionRef = useRef(0);
  const mutedRef = useRef(muted);
  const seen = useRef(previouslyPlayed());
  const available = useRef(new Set<string>());
  const queue = useRef<ReminderNotice[]>([]);
  const audio = useRef<HTMLAudioElement | null>(null);
  const working = useRef(false);
  const revision = useRef(0);
  const finish = useRef<(() => void) | null>(null);

  const stop = useCallback(() => {
    revision.current += 1;
    queue.current = [];
    audio.current?.pause();
    finish.current?.();
    setPlaying("");
  }, []);

  const pump = useCallback(async () => {
    if (working.current) return;
    working.current = true;
    try {
      while (queue.current.length && !mutedRef.current) {
        const notice = queue.current.shift()!;
        const before = revision.current;
        if (!available.current.has(keyOf(notice)) || !notice.audio_path) continue;
        const snapshotVersion = policyVersionRef.current;
        const [visible, policyResult] = await Promise.all([
          isReminderWindowVisible().catch(() => false),
          getChatSnapshot({ claimRenderer: false })
            .then((snapshot) => ({ failed: false as const, snapshot }))
            .catch(() => ({ failed: true as const, snapshot: null })),
        ]);
        if (before !== revision.current) continue;
        if (snapshotVersion === policyVersionRef.current) {
          if (!policyResult.failed && policyResult.snapshot !== null) {
            const disabled = Boolean(policyResult.snapshot.characterSpeechDisabled);
            sessionPolicyRef.current = disabled;
            speechDisabledRef.current = disabled;
            setSpeechDisabled(disabled);
          } else if (policyResult.failed) {
            if (sessionPolicyRef.current !== null) {
              speechDisabledRef.current = sessionPolicyRef.current;
              setSpeechDisabled(sessionPolicyRef.current);
            }
          }
        }
        if (!visible || speechDisabledRef.current || sessionPolicyRef.current === null) continue;
        const player = new Audio(fileUrl(notice.audio_path));
        player.volume = Math.max(0, Math.min(1, notice.audio_volume ?? 1));
        audio.current = player;
        setPlaying(keyOf(notice));
        await new Promise<void>((resolve) => {
          finish.current = resolve;
          player.onended = () => resolve();
          player.onerror = () => resolve();
          // WebView autoplay failures leave the manual replay action available.
          void player.play().catch(() => resolve());
        });
        player.onended = null;
        player.onerror = null;
        finish.current = null;
        audio.current = null;
        setPlaying("");
      }
    } finally {
      working.current = false;
    }
  }, []);

  useEffect(
    () =>
      subscribeChat(
        (snapshot) => {
          policyVersionRef.current += 1;
          const disabled = Boolean(snapshot.characterSpeechDisabled);
          sessionPolicyRef.current = disabled;
          speechDisabledRef.current = disabled;
          setSpeechDisabled(disabled);
          if (disabled) stop();
        },
        { claimRenderer: false },
      ),
    [stop],
  );

  useEffect(() => {
    available.current = new Set(notices.map(keyOf));
    const fresh = [...notices].reverse().filter((notice) => notice.audio_path && !seen.current.has(keyOf(notice)));
    for (const notice of fresh) seen.current.add(keyOf(notice));
    try {
      sessionStorage.setItem(playedStorage, JSON.stringify([...seen.current].slice(-512)));
    } catch {
      /* Optional cache. */
    }
    if (!mutedRef.current) queue.current.push(...fresh);
    void pump();
  }, [notices, pump]);

  useEffect(() => {
    const listener = onReminderWindowHidden(stop).catch(() => () => {});
    return () => {
      stop();
      void listener.then((unlisten) => unlisten());
    };
  }, [stop]);

  const toggleMute = () => {
    if (speechDisabledRef.current) return;
    mutedRef.current = !mutedRef.current;
    setMuted(mutedRef.current);
    try {
      localStorage.setItem("shinsekai.reminder.muted", String(mutedRef.current));
    } catch {
      /* Session-only mute. */
    }
    if (mutedRef.current) stop();
  };

  const replay = (notice: ReminderNotice) => {
    stop();
    if (mutedRef.current || speechDisabledRef.current || !notice.audio_path) return;
    queue.current.push(notice);
    void pump();
  };

  return { muted: muted || speechDisabled, speechDisabled, playing, toggleMute, replay, stop };
}
