import {
  DEFAULT_SPRITE_GROUP,
  LLM_PROVIDER_DOUBAO,
  LLM_PROVIDER_QWEN,
  LLM_PROVIDER_SILICONFLOW,
  TRANSPARENT_BACKGROUND_NAME,
} from "../constants";
import type { Character } from "../platform/types";
import { isSelfPersonaCharacter, isSelfPersonaName } from "../playerCharacterOptions";
import type { TranslateFn } from "./I18nProvider";

export function formatLlmProviderLabel(value: string, t: TranslateFn, fallbackLabel?: string): string {
  const clean = (value ?? "").trim();
  switch (clean) {
    case LLM_PROVIDER_DOUBAO:
      return t("domain.llmProvider.doubao");
    case LLM_PROVIDER_QWEN:
      return t("domain.llmProvider.qwen");
    case LLM_PROVIDER_SILICONFLOW:
      return t("domain.llmProvider.siliconflow");
    default:
      return fallbackLabel?.trim() || clean;
  }
}

export function formatBackgroundName(value: string, t: TranslateFn): string {
  const clean = (value ?? "").trim();
  if (clean === TRANSPARENT_BACKGROUND_NAME) {
    return t("domain.background.transparent");
  }
  return clean;
}

export function formatCharacterDisplayName(
  character:
    | (Pick<Character, "name" | "display_name"> & Partial<Pick<Character, "id" | "is_builtin" | "undeletable">>)
    | string,
  t: TranslateFn,
): string {
  if (typeof character === "string") {
    const clean = character.trim();
    return isSelfPersonaName(clean) ? t("domain.character.selfPersona") : clean;
  }
  const cleanName = character.name.trim();
  if (isSelfPersonaCharacter(character) && isSelfPersonaName(cleanName)) {
    return character.display_name?.trim() || t("domain.character.selfPersona");
  }
  return character.name;
}

export function formatSpriteGroupLabel(value: string | undefined | null, t: TranslateFn): string {
  const clean = (value ?? "").trim();
  if (!clean || clean === DEFAULT_SPRITE_GROUP) {
    return t("domain.spriteGroup.default");
  }
  return clean;
}
