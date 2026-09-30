import type { AvatarSession } from "./contracts";

// Only chat instances bind here; previews have no character voice route.
const targets = new Map<string, Set<AvatarSession<unknown, unknown>>>();

export function bindAvatarVoice(name: string, session: AvatarSession<unknown, unknown>) {
  if (!name) return () => {};
  const instances = targets.get(name) ?? new Set<AvatarSession<unknown, unknown>>();
  instances.add(session);
  targets.set(name, instances);
  return () => {
    if (session.capabilities.mouth) session.setMouthOpen(0);
    instances.delete(session);
    if (!instances.size) targets.delete(name);
  };
}

export function routeAvatarVoice(name: string, value: number) {
  for (const session of targets.get(name) ?? []) if (session.capabilities.mouth) session.setMouthOpen(value);
}
