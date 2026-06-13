import type { Character, CharacterScenario } from "../../entities/config/types";
import { getPlatform } from "../../shared/platform/platform";

export function listCharacters() {
  return getPlatform()
    .config.get()
    .then((config) => config.characters);
}

export function saveCharacter(character: Character, originalName?: string) {
  return getPlatform().characters.save(character, originalName);
}

export function deleteCharacter(name: string) {
  return getPlatform().characters.delete(name);
}

export function importCharacters(paths: string[]) {
  return getPlatform().characters.import(paths);
}

export function exportCharacter(name: string) {
  return getPlatform().characters.export(name);
}

export function generateCharacterSetting(input: { name: string; setting: string }) {
  return getPlatform().characters.generateSetting(input);
}

export function translateCharacterFields(input: { name: string; characterSetting: string; emotionTags: string }) {
  return getPlatform().characters.translateFields(input);
}

export function uploadCharacterSprites(input: { name: string; paths: string[]; emotionTags: string }) {
  return getPlatform().characters.uploadSprites(input);
}

export function deleteCharacterSprite(name: string, index: number) {
  return getPlatform().characters.deleteSprite(name, index);
}

export function deleteAllCharacterSprites(name: string) {
  return getPlatform().characters.deleteAllSprites(name);
}

export function saveCharacterEmotionTags(name: string, emotionTags: string) {
  return getPlatform().characters.saveEmotionTags(name, emotionTags);
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

// ---------- 情景模块 ----------

export function saveCharacterScenarios(name: string, scenarios: CharacterScenario[]) {
  return getPlatform().characters.saveScenarios(name, scenarios);
}

export function uploadScenarioVoice(input: {
  name: string;
  scenarioIndex: number;
  voicePath: string;
  voiceText: string;
  voiceType: string;
}) {
  return getPlatform().characters.uploadScenarioVoice(input);
}

export function deleteScenarioVoice(name: string, scenarioIndex: number) {
  return getPlatform().characters.deleteScenarioVoice(name, scenarioIndex);
}

export function saveScenarioVoiceText(input: { name: string; scenarioIndex: number; voiceText: string }) {
  return getPlatform().characters.saveScenarioVoiceText(input);
}

export function saveScenarioVoiceType(input: { name: string; scenarioIndex: number; voiceType: string }) {
  return getPlatform().characters.saveScenarioVoiceType(input);
}

// ---------- memory ----------

export function listCharacterMemories(name: string) {
  return getPlatform().characters.listMemories(name);
}

export function rememberCharacterMemory(name: string, content: string) {
  return getPlatform().characters.remember(name, content);
}

export function deleteCharacterMemory(name: string, memoryId: string) {
  return getPlatform().characters.deleteMemory(name, memoryId);
}

export const charactersQueryKey = ["characters"] as const;
