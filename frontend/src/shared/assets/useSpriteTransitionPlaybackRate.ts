import { useSyncExternalStore } from "react";

import { SPRITE_TRANSITION_PLAYBACK_RATE, SPRITE_TRANSITION_PLAYBACK_RATES } from "./spriteTransition";

export const SPRITE_TRANSITION_RATE_STORAGE_KEY = "shinsekai-sprite-transition-playback-rate";
const listeners = new Set<() => void>();
let rate: number = SPRITE_TRANSITION_PLAYBACK_RATE;
let memoryOnly = false;

function normalize(value: unknown): number {
  return typeof value === "number" && SPRITE_TRANSITION_PLAYBACK_RATES.some((item) => item === value)
    ? value
    : SPRITE_TRANSITION_PLAYBACK_RATE;
}

function readSavedRate(): number {
  if (typeof window === "undefined" || memoryOnly) return rate;
  try {
    const raw = window.localStorage.getItem(SPRITE_TRANSITION_RATE_STORAGE_KEY);
    return raw === null ? SPRITE_TRANSITION_PLAYBACK_RATE : normalize(JSON.parse(raw));
  } catch {
    return rate;
  }
}

rate = readSavedRate();

function notify() {
  listeners.forEach((listener) => listener());
}

function changed(event: StorageEvent) {
  if (event.key !== null && event.key !== SPRITE_TRANSITION_RATE_STORAGE_KEY) return;
  memoryOnly = false;
  try {
    rate = normalize(event.newValue === null ? undefined : JSON.parse(event.newValue));
  } catch {
    rate = SPRITE_TRANSITION_PLAYBACK_RATE;
  }
  notify();
}

function subscribe(listener: () => void) {
  if (!listeners.size && typeof window !== "undefined") {
    rate = readSavedRate();
    window.addEventListener("storage", changed);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (!listeners.size && typeof window !== "undefined") window.removeEventListener("storage", changed);
  };
}

export function setSpriteTransitionPlaybackRate(value: number) {
  rate = normalize(value);
  try {
    window.localStorage.setItem(SPRITE_TRANSITION_RATE_STORAGE_KEY, JSON.stringify(rate));
    memoryOnly = false;
  } catch {
    memoryOnly = true;
  }
  notify();
}

export function useSpriteTransitionPlaybackRate() {
  return useSyncExternalStore(
    subscribe,
    () => rate,
    () => SPRITE_TRANSITION_PLAYBACK_RATE,
  );
}
