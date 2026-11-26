import type { Effect } from "../../entities/config/types";

export const EFFECT_RESOURCES_URL = "https://shinsekai.end0rph1n.icu/resources";

export function createEffect(): Effect {
  return {
    name: "",
    color: "#5b8def",
    prompt_text: "",
    audio_list: [],
    audio_tags: "",
    image_list: [],
    image_tags: "",
    image_audio_list: [],
    ambient_list: [],
    ambient_tags: "",
    ambient_audio_list: [],
    ambient_layers: [],
  };
}

export function normalizeEffect(effect: Effect): Effect {
  return {
    ...effect,
    ambient_list: effect.ambient_list ?? [],
    ambient_tags: effect.ambient_tags ?? "",
    ambient_audio_list: effect.ambient_audio_list ?? [],
    ambient_layers: effect.ambient_layers ?? [],
  };
}

export function upsertCatalogEffect(current: Effect[], effect: Effect, originalName?: string): Effect[] {
  const targetNames = new Set([originalName, effect.name].filter(Boolean).map((item) => String(item).toLowerCase()));
  const next: Effect[] = [];
  let replaced = false;
  for (const item of current) {
    const matchedById = Boolean(effect.id && item.id && item.id === effect.id);
    if (matchedById || targetNames.has(item.name.toLowerCase())) {
      if (!replaced) {
        next.push(effect);
        replaced = true;
      }
      continue;
    }
    next.push(item);
  }
  if (!replaced) {
    next.push(effect);
  }
  return next;
}

export function buildCreateEffectPayload(draft: Effect): Effect {
  const { id: _omittedId, ...restDraft } = draft;
  return {
    ...restDraft,
    color: draft.color.trim() || "#5b8def",
    name: draft.name.trim(),
  };
}

export function serializeEffectNonIdentity(
  effect: Pick<Effect, "audio_tags" | "color" | "image_tags" | "prompt_text">,
): string {
  return JSON.stringify({
    audio_tags: effect.audio_tags ?? "",
    color: (effect.color ?? "").trim() || "#5b8def",
    image_tags: effect.image_tags ?? "",
    prompt_text: effect.prompt_text ?? "",
  });
}
