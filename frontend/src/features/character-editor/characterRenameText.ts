import type { Character } from "../../entities/config/types";

export interface CharacterRenameTextPreview {
  briefMatches: number;
  newName: string;
  nextBrief: string;
  nextSetting: string;
  oldName: string;
  settingMatches: number;
  totalMatches: number;
}

const ASCII_WORD_START_RE = /^[A-Za-z0-9_]/;
const ASCII_WORD_END_RE = /[A-Za-z0-9_]$/;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function buildCharacterNameMatchPattern(oldName: string): RegExp | null {
  const trimmed = oldName.trim();
  if (!trimmed) {
    return null;
  }
  const prefix = ASCII_WORD_START_RE.test(trimmed) ? "(?<![A-Za-z0-9_])" : "";
  const suffix = ASCII_WORD_END_RE.test(trimmed) ? "(?![A-Za-z0-9_])" : "";
  return new RegExp(`${prefix}${escapeRegExp(trimmed)}${suffix}`, "g");
}

function replaceAndCount(source: string, pattern: RegExp, newName: string): { next: string; count: number } {
  if (!source) {
    return { next: source, count: 0 };
  }
  let count = 0;
  const next = source.replace(pattern, () => {
    count += 1;
    return newName;
  });
  return { next, count };
}

export function previewCharacterRenameText(
  character: Pick<Character, "character_brief" | "character_setting">,
  oldName: string,
  newName: string,
): CharacterRenameTextPreview {
  const trimmedOld = oldName.trim();
  const trimmedNew = newName.trim();
  const setting = character.character_setting ?? "";
  const brief = character.character_brief ?? "";
  if (!trimmedOld || !trimmedNew || trimmedOld === trimmedNew) {
    return {
      briefMatches: 0,
      newName: trimmedNew,
      nextBrief: brief,
      nextSetting: setting,
      oldName: trimmedOld,
      settingMatches: 0,
      totalMatches: 0,
    };
  }
  const pattern = buildCharacterNameMatchPattern(trimmedOld);
  if (!pattern) {
    return {
      briefMatches: 0,
      newName: trimmedNew,
      nextBrief: brief,
      nextSetting: setting,
      oldName: trimmedOld,
      settingMatches: 0,
      totalMatches: 0,
    };
  }
  const settingResult = replaceAndCount(setting, pattern, trimmedNew);
  const briefResult = replaceAndCount(brief, pattern, trimmedNew);
  return {
    briefMatches: briefResult.count,
    newName: trimmedNew,
    nextBrief: briefResult.next,
    nextSetting: settingResult.next,
    oldName: trimmedOld,
    settingMatches: settingResult.count,
    totalMatches: settingResult.count + briefResult.count,
  };
}
