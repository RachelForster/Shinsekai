import type { AvatarSpeechEvent } from "./contracts";

interface VoiceTarget {
  capabilities?: { mouth: boolean };
  setMouthOpen?(value: number): void;
  setSpeechLevel?(value: number): void;
  setSpeechActivity?(value: number): void;
  notifySpeechEvent?(event: AvatarSpeechEvent): void;
}

// Only chat instances bind here; previews have no character voice route.
const targets = new Map<string, Set<VoiceTarget>>();
const currentSpeech = new Map<string, { level: number | null; activity: number | null }>();

export function bindAvatarVoice(name: string, session: VoiceTarget) {
  if (!name) return () => {};
  const instances = targets.get(name) ?? new Set<VoiceTarget>();
  instances.add(session);
  targets.set(name, instances);
  const current = currentSpeech.get(name);
  if (current) {
    session.notifySpeechEvent?.("started");
    if (current.level !== null) {
      session.setSpeechLevel?.(current.level);
      session.setSpeechActivity?.(current.activity ?? current.level);
      if (session.capabilities?.mouth) session.setMouthOpen?.(current.level);
    }
  }
  return () => {
    session.setSpeechLevel?.(0);
    session.setSpeechActivity?.(0);
    if (session.capabilities?.mouth) session.setMouthOpen?.(0);
    instances.delete(session);
    if (!instances.size) targets.delete(name);
  };
}

export function routeAvatarVoice(name: string, value: number, instantLevel = value) {
  const current = currentSpeech.get(name);
  if (current) {
    current.level = value;
    current.activity = instantLevel;
  }
  for (const session of targets.get(name) ?? []) {
    session.setSpeechLevel?.(value);
    session.setSpeechActivity?.(instantLevel);
    if (session.capabilities?.mouth) session.setMouthOpen?.(value);
  }
}

export function routeAvatarSpeechEvent(name: string, event: AvatarSpeechEvent) {
  if (event === "started") currentSpeech.set(name, { level: null, activity: null });
  else currentSpeech.delete(name);
  for (const session of targets.get(name) ?? []) session.notifySpeechEvent?.(event);
}
