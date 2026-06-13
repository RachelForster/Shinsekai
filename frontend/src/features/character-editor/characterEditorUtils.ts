import type { Character } from "../../entities/config/types";
import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";

export const CHARACTER_RESOURCES_URL = "https://shinsekai.end0rph1n.icu/resources";

export const SPRITE_SCALE_MIN = 0;
export const SPRITE_SCALE_MAX = 3;
export const SPRITE_SCALE_STEP = 0.05;

export type CharacterFieldChange = <K extends keyof Character>(name: K, value: Character[K]) => void;

export type CharacterResourceDeleteTarget =
  | { characterName: string; index: number; kind: "sprite"; filename: string }
  | { characterName: string; count: number; kind: "all-sprites" }
  | { characterName: string; index: number; kind: "sprite-voice"; filename: string }
  | { characterName: string; kind: "memory"; memory: string; memoryId: string };

export function createCharacter(): Character {
  return {
    character_setting: "",
    color: DEFAULT_CHARACTER_COLOR,
    emotion_tags: "",
    scenarios: [],
    name: "",
    pronunciation_map: {},
    speech_speed: 1,
    speech_volume: 1,
    sprite_prefix: "temp",
    sprite_scale: 1,
    sprites: [],
  };
}

export function pronunciationMapToText(value: Record<string, string>) {
  return Object.entries(value ?? {})
    .map(([key, item]) => `${key}=${item}`)
    .join("\n");
}

export function pronunciationTextToMap(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, line) => {
      const index = line.indexOf("=");
      if (index <= 0) {
        return acc;
      }
      const key = line.slice(0, index).trim();
      const item = line.slice(index + 1).trim();
      if (key) {
        acc[key] = item;
      }
      return acc;
    }, {});
}

export function clampSpriteScale(value: number) {
  return Math.min(SPRITE_SCALE_MAX, Math.max(SPRITE_SCALE_MIN, Number(value.toFixed(2))));
}
