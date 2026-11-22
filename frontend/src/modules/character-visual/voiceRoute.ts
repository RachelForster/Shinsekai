import type { AvatarSession, AvatarSpeechEvent } from "./contracts";

// Only chat instances bind here; previews have no character voice route.
const targets = new Map<string, Set<AvatarSession<unknown, unknown>>>();
const mouthLevels = new Map<string, Set<(value: number) => void>>();

export function bindMouthLevel(name: string, listener: (value: number) => void) {
  const listeners = mouthLevels.get(name) ?? new Set<(value: number) => void>();
  listeners.add(listener);
  mouthLevels.set(name, listeners);
  return () => {
    listener(0);
    listeners.delete(listener);
    if (!listeners.size) mouthLevels.delete(name);
  };
}

export function bindAvatarVoice(name: string, session: AvatarSession<unknown, unknown>) {
  if (!name) return () => {};
  const instances = targets.get(name) ?? new Set<AvatarSession<unknown, unknown>>();
  instances.add(session);
  targets.set(name, instances);
  return () => {
    session.setSpeechLevel?.(0);
    if (session.capabilities.mouth) session.setMouthOpen(0);
    instances.delete(session);
    if (!instances.size) targets.delete(name);
  };
}

export function routeAvatarVoice(name: string, value: number) {
  for (const listener of mouthLevels.get(name) ?? []) listener(value);
  for (const session of targets.get(name) ?? []) {
    session.setSpeechLevel?.(value);
    if (session.capabilities.mouth) session.setMouthOpen(value);
  }
}

export function routeAvatarSpeechEvent(name: string, event: AvatarSpeechEvent) {
  if (event === "finished") for (const listener of mouthLevels.get(name) ?? []) listener(0);
  for (const session of targets.get(name) ?? []) session.notifySpeechEvent?.(event);
}
