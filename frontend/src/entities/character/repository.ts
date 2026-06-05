import { getPlatform } from "../../shared/platform/platform";
import type { Character } from "../config/types";

export const charactersQueryKey = ["characters"] as const;

export function listCharacters() {
  return getPlatform().characters.list();
}

export function saveCharacter(character: Character, originalName?: string) {
  return getPlatform().characters.save(character, originalName);
}

export function deleteCharacter(name: string) {
  return getPlatform().characters.delete(name);
}

export function importCharacters(items: File[] | string[]) {
  return getPlatform().characters.import(items);
}

export function exportCharacter(name: string) {
  return getPlatform().characters.export(name);
}

export function generateCharacterSetting(input: { name: string; setting: string }) {
  return getPlatform().characters.generateSetting(input);
}

export function translateCharacterFields(input: { characterSetting: string; emotionTags: string; name: string }) {
  return getPlatform().characters.translateFields(input);
}

export function listCharacterMemories(name: string) {
  return getPlatform().characters.listMemories(name);
}

export function rememberCharacterMemory(name: string, content: string) {
  return getPlatform().characters.remember(name, content);
}

export function deleteCharacterMemory(name: string, memoryId: string) {
  return getPlatform().characters.deleteMemory(name, memoryId);
}

export function uploadCharacterSprites(input: { emotionTags: string; name: string; paths: string[] }) {
  return getPlatform().characters.uploadSprites(input);
}

export function saveCharacterEmotionTags(name: string, emotionTags: string) {
  return getPlatform().characters.saveEmotionTags(name, emotionTags);
}

export function deleteCharacterSprite(name: string, spriteIndex: number) {
  return getPlatform().characters.deleteSprite(name, spriteIndex);
}

export function deleteAllCharacterSprites(name: string) {
  return getPlatform().characters.deleteAllSprites(name);
}

export function saveSpriteScale(name: string, scale: number) {
  return getPlatform().characters.saveSpriteScale(name, scale);
}

export function uploadSpriteVoice(input: { name: string; spriteIndex: number; voicePath: string; voiceText: string }) {
  return getPlatform().characters.uploadSpriteVoice(input);
}

export function saveSpriteVoiceText(name: string, spriteIndex: number, voiceText: string) {
  return getPlatform().characters.saveSpriteVoiceText(name, spriteIndex, voiceText);
}

export function deleteSpriteVoice(name: string, spriteIndex: number) {
  return getPlatform().characters.deleteSpriteVoice(name, spriteIndex);
}
