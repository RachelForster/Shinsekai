import { LEGACY_TRANSPARENT_BACKGROUND_ALIAS, TRANSPARENT_BACKGROUND_NAME } from "../../../constants";
import { translateRuntimeMessage } from "../../../i18n/runtimeLanguage";
import {
  SELF_PERSONA_ID,
  SELF_PERSONA_NAME,
  SELF_PERSONA_SPRITE_PREFIX,
  findSelfPersona,
  isSelfPersonaCharacter,
  isSelfPersonaId,
  isSelfPersonaName,
} from "../../../playerCharacterOptions";
import type { Character } from "../../slices/characterTypes";
import type { MediaSelectionMode } from "../../slices/workspaceTypes";
import { createStandaloneTemplateTranslator } from "./standaloneTemplateLocales";
import {
  isUiVoiceSameLanguage as isUiVoiceSameTarget,
  targetVoiceKey as resolveVoiceTargetKey,
  type VoiceTargetKey,
} from "./voiceLanguage";

export {
  SELF_PERSONA_ID,
  SELF_PERSONA_NAME,
  SELF_PERSONA_SPRITE_PREFIX,
  findSelfPersona,
  isSelfPersonaCharacter,
  isSelfPersonaId,
  isSelfPersonaName,
};

export const TRANSPARENT_BG = TRANSPARENT_BACKGROUND_NAME;
const TRANSPARENT_BG_ALIAS = LEGACY_TRANSPARENT_BACKGROUND_ALIAS;
export const DEFAULT_EMPTY_SCENARIO = createStandaloneTemplateTranslator("zh_CN")("default_empty_scenario");

export function characterNameKey(name: string): string {
  return name.trim().toLowerCase();
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

export function targetVoiceKey(code?: string | null): VoiceTargetKey | "auto" {
  return resolveVoiceTargetKey(code);
}

export function isUiVoiceSameLanguage(uiLanguage?: string, voiceLanguage?: string): boolean {
  return isUiVoiceSameTarget(uiLanguage, resolveVoiceTargetKey(voiceLanguage || "ja"));
}

export function composeTemplateContent(scenario: string, system: string): string {
  return [scenario.trim(), system.trim()].filter(Boolean).join("\n\n");
}

export function findCharacterByName(characters: Character[], rawName: string): Character | undefined {
  const key = characterNameKey(rawName);
  if (!key) return undefined;
  const exact = characters.find((c) => characterNameKey(c.name) === key);
  if (exact) return exact;
  if (isSelfPersonaName(rawName) || isSelfPersonaId(rawName)) {
    return findSelfPersona(characters);
  }
  return undefined;
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
  if (!isSelfPersonaCharacter(character) && !castKeys.has(characterNameKey(character.name))) {
    throw new Error(translateRuntimeMessage("plat.standalone.playerMustBeValid", undefined, uiLanguage));
  }
  return character.name;
}
