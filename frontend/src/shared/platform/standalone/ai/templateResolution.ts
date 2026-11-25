import {
  DEFAULT_SPRITE_GROUP,
  LANG_ALIAS_CHINESE_ZH,
  LANG_ALIAS_ENGLISH_ZH,
  LEGACY_TRANSPARENT_BACKGROUND_ALIAS,
  TRANSPARENT_BACKGROUND_NAME,
} from "../../../constants";
import { translateRuntimeMessage } from "../../../i18n/runtimeLanguage";
import { SELF_PERSONA_NAME } from "../../../playerCharacterOptions";
import type { Character } from "../../slices/characterTypes";
import type { MediaSelectionMode } from "../../slices/workspaceTypes";
import { createStandaloneTemplateTranslator } from "./standaloneTemplateLocales";

export { SELF_PERSONA_NAME };
export const TRANSPARENT_BG = TRANSPARENT_BACKGROUND_NAME;
const TRANSPARENT_BG_ALIAS = LEGACY_TRANSPARENT_BACKGROUND_ALIAS;
export const DEFAULT_EMPTY_SCENARIO = createStandaloneTemplateTranslator("zh_CN")("default_empty_scenario");

export function characterNameKey(name: string): string {
  return name.trim().toLowerCase();
}

export function isSelfPersonaName(name: string | undefined | null): boolean {
  return characterNameKey(String(name ?? "")) === SELF_PERSONA_NAME;
}

export function resolveCharacterPromptName(
  character: Pick<Character, "name" | "display_name"> | undefined | null,
  collidingNames: Iterable<string> = [],
  fallbackName = "",
): string {
  const rawName = String(character?.name ?? fallbackName ?? "").trim();
  if (isSelfPersonaName(rawName)) {
    const displayName = String(character?.display_name ?? "").trim();
    const collisionKeys = new Set<string>();
    for (const item of collidingNames) {
      const cleaned = String(item ?? "").trim();
      if (cleaned && !isSelfPersonaName(cleaned)) {
        collisionKeys.add(characterNameKey(cleaned));
      }
    }
    if (displayName && !collisionKeys.has(characterNameKey(displayName))) {
      return displayName;
    }
  }
  return rawName || String(fallbackName ?? "").trim();
}

export function findCharacterByName(characters: Character[], rawName: string): Character | undefined {
  const key = characterNameKey(rawName);
  if (!key) return undefined;
  return characters.find((c) => characterNameKey(c.name) === key);
}

export function findCharacterByPromptName(characters: Character[], rawName: string): Character | undefined {
  const key = characterNameKey(rawName);
  if (!key) return undefined;
  const direct = findCharacterByName(characters, rawName);
  if (direct) return direct;
  return characters.find((c) => {
    if (!isSelfPersonaName(c.name)) return false;
    const displayName = String(c.display_name ?? "").trim();
    return Boolean(displayName) && characterNameKey(displayName) === key;
  });
}

export function isTransparentBackground(name?: string | null): boolean {
  const clean = String(name ?? "").trim();
  return !clean || clean === TRANSPARENT_BG || clean === TRANSPARENT_BG_ALIAS;
}

export function normalizeMediaSelectionMode(mode: unknown): MediaSelectionMode {
  return String(mode ?? "")
    .trim()
    .toLowerCase() === "semantic"
    ? "semantic"
    : "indexed";
}

export function targetVoiceKey(code?: string | null): "ja" | "en" | "zh" | "yue" {
  const raw = String(code ?? "").trim() || "ja";
  const low = raw.toLowerCase();
  if (low === "yue" || low === "yue_hk" || low === "cantonese" || low === "cht" || low === "zh_hk") {
    return "yue";
  }
  if (low.startsWith("en") || low === "english" || low === LANG_ALIAS_ENGLISH_ZH) {
    return "en";
  }
  if (low.startsWith("zh") || low === "chinese" || low === LANG_ALIAS_CHINESE_ZH) {
    return "zh";
  }
  return "ja";
}

export function isUiVoiceSameLanguage(uiLanguage?: string, voiceLanguage?: string): boolean {
  const uiNorm = String(uiLanguage ?? "zh_CN").trim();
  const uiMain = uiNorm.split(/[-_]/)[0].toLowerCase() || "zh";
  const voiceMain = targetVoiceKey(voiceLanguage);
  return uiMain === voiceMain;
}

export function composeTemplateContent(scenario: string, system: string): string {
  return [scenario.trim(), system.trim()].filter(Boolean).join("\n\n");
}

export function resolveTemplateCharacters(selectedNames: string[], allCharacters: Character[]): Character[] {
  const seenKeys = new Set<string>();
  const resolved: Character[] = [];
  for (const raw of selectedNames) {
    const clean = String(raw ?? "").trim();
    if (!clean) continue;
    const reqKey = characterNameKey(clean);
    if (seenKeys.has(reqKey)) continue;
    seenKeys.add(reqKey);

    const found = findCharacterByName(allCharacters, clean);
    if (!found) continue;
    const canonKey = characterNameKey(found.name);
    if (resolved.some((c) => characterNameKey(c.name) === canonKey)) continue;
    resolved.push(found);
  }
  return resolved;
}

export function resolvePlayerCharacter(
  allCharacters: Character[],
  resolvedCastNames: string[],
  rawPlayerName: unknown,
  uiLanguage?: string,
): string {
  const name = String(rawPlayerName ?? "").trim();
  if (!name) return "";
  const character = findCharacterByName(allCharacters, name);
  if (!character) {
    throw new Error(translateRuntimeMessage("plat.standalone.playerMustBeValid", undefined, uiLanguage));
  }
  const castKeys = new Set(resolvedCastNames.map((n) => characterNameKey(n)));
  if (!isSelfPersonaName(character.name) && !castKeys.has(characterNameKey(character.name))) {
    throw new Error(translateRuntimeMessage("plat.standalone.playerMustBeValid", undefined, uiLanguage));
  }
  return character.name;
}

export function spriteGroupOf(group: string | null | undefined): string {
  return String(group ?? "").trim() || DEFAULT_SPRITE_GROUP;
}

export function listNonEmptySpriteGroups(character: Character): string[] {
  const sprites = character.sprites ?? [];
  const present = new Set<string>();
  const presentOrder: string[] = [];
  for (const sprite of sprites) {
    const grp = spriteGroupOf(sprite.group);
    if (!present.has(grp)) {
      present.add(grp);
      presentOrder.push(grp);
    }
  }
  const configured = (character.sprite_groups ?? []).map((g) => spriteGroupOf(g));
  const ordered = configured.filter((g) => present.has(g));
  for (const grp of presentOrder) {
    if (!ordered.includes(grp)) ordered.push(grp);
  }
  return ordered;
}

export function resolveDefaultSpriteGroup(character: Character): string {
  const present = listNonEmptySpriteGroups(character);
  const configured = String(character.default_sprite_group ?? "").trim();
  if (configured) {
    const norm = spriteGroupOf(configured);
    if (!present.length || present.includes(norm)) {
      return norm;
    }
  }
  if (!present.length || present.includes(DEFAULT_SPRITE_GROUP)) {
    return DEFAULT_SPRITE_GROUP;
  }
  return present[0];
}
