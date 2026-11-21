import type { Sprite } from "./characterTypes";
import type { ImageAutoLabelResult, TaskProgressOptions } from "./taskTypes";

export interface Background {
  name: string;
  sprite_prefix: string;
  sprites: Sprite[];
  bg_tags: string;
  bgm_list: string[];
  bgm_tags: string;
}

export interface BackgroundTranslateResult {
  bgTags: string;
  bgmRowTags?: string[];
  bgmTags: string;
  error?: string;
  name: string;
}

export interface BackgroundTranslateInput {
  bgTags: string;
  bgmRowTags?: string[];
  bgmTags: string;
  name: string;
}

export interface Effect {
  name: string;
  color: string;
  prompt_text: string;
  audio_list: string[];
  audio_tags: string;
  image_list: string[];
  image_tags: string;
  image_audio_list: string[];
}

export interface PlayerCharacterOptions {
  playerCharacter?: string;
  readPlayerSpeech?: boolean;
  allowPlayerDialogue?: boolean;
}

export type CharacterPromptMode = "compact" | "full";
export type MediaSelectionMode = "indexed" | "semantic";
export type MemoryMode = "isolated" | "shared" | "inherit_readonly";
export type InitialOutfitValue = string | { activeGroup: string; locked?: boolean };

export interface UserPromptPreset {
  id: string;
  name: string;
  group: string;
  color?: string;
  content: string;
}

export interface AppliedUserPromptPreset {
  id: string;
  name: string;
  group?: string;
  color?: string;
  content: string;
}

export interface UserPromptPresetLibrary {
  groups: string[];
  presets: UserPromptPreset[];
}

export interface TemplateSummary extends PlayerCharacterOptions {
  appliedPresets?: AppliedUserPromptPreset[];
  baseScenario?: string;
  content: string;
  generationMessage?: string;
  id: string;
  name: string;
  path: string;
  mediaSelectionMode?: MediaSelectionMode;
  scenario?: string;
  selectedPresetIds?: string[];
  system?: string;
  updatedAt: string;
}

export interface TemplateGenerationResult extends TemplateSummary {
  resolvedCharacters: string[];
}

export interface TemplateGenerateInput extends PlayerCharacterOptions {
  backgroundName: string;
  characterPromptMode?: CharacterPromptMode;
  characters: string[];
  effectNames?: string[];
  maxDialogItems?: number;
  maxSpeechChars?: number;
  mediaSelectionMode?: MediaSelectionMode;
  name: string;
  primaryCharacters?: string[];
  scenario?: string;
  useCg?: boolean;
  useChoice?: boolean;
  useCot?: boolean;
  useEffect?: boolean;
  useNarration?: boolean;
  useStat?: boolean;
  useTranslation?: boolean;
  voiceLanguage?: string;
}

export interface TemplateLaunchSession extends PlayerCharacterOptions {
  appliedPresets?: AppliedUserPromptPreset[];
  background: string;
  baseScenario?: string;
  characterPromptMode?: CharacterPromptMode;
  enableMobileAccess?: boolean;
  effectNames: string[];
  filenameStub: string;
  historyPath: string;
  initSpritePath: string;
  showInitialSprite?: boolean;
  maxDialogItems: number;
  maxSpeechChars: number;
  mediaSelectionMode?: MediaSelectionMode;
  memoryMode?: MemoryMode;
  autoOutfitSwitch?: boolean;
  initialOutfits?: Record<string, InitialOutfitValue>;
  roomId: string;
  scenario: string;
  selectedPresetIds?: string[];
  primaryCharacters?: string[];
  selectedCharacters: string[];
  system: string;
  systemManuallyEdited?: boolean;
  templateFileDropdown: string;
  useCg: boolean;
  useChoice: boolean;
  useCot: boolean;
  useEffect: boolean;
  useNarration: boolean;
  useStat: boolean;
  useTranslation: boolean;
  voiceLanguage: string;
}

export interface SpritePromptResult {
  prompts: string[];
}

export interface SpriteGenerationResult {
  files: string[];
  message: string;
  outputDir: string;
}

export interface BatchToolResult {
  message: string;
  outputDir: string;
}

export interface BackgroundsPlatform {
  autoLabelImages: (name: string, options?: TaskProgressOptions<ImageAutoLabelResult>) => Promise<ImageAutoLabelResult>;
  delete: (name: string) => Promise<void>;
  deleteAllBgm: (name: string) => Promise<Background>;
  deleteAllImages: (name: string) => Promise<Background>;
  deleteBgm: (name: string, index: number) => Promise<Background>;
  deleteImage: (name: string, index: number) => Promise<Background>;
  export: (name: string) => Promise<string>;
  import: (items: File[] | string[]) => Promise<Background[]>;
  list: () => Promise<Background[]>;
  save: (background: Background, originalName?: string) => Promise<Background>;
  saveBgmTags: (input: { bgmTags: string; name: string }) => Promise<Background>;
  saveImageTags: (input: { bgTags: string; name: string }) => Promise<Background>;
  translateFields: (input: BackgroundTranslateInput) => Promise<BackgroundTranslateResult>;
  uploadBgm: (input: { bgmTags: string; name: string; paths: string[] }) => Promise<Background>;
  uploadImages: (input: { bgTags: string; name: string; paths: string[] }) => Promise<Background>;
}

export interface EffectsPlatform {
  delete: (name: string) => Promise<void>;
  deleteAllAudio: (name: string) => Promise<Effect>;
  deleteAudio: (name: string, index: number) => Promise<Effect>;
  deleteImage: (name: string, index: number) => Promise<Effect>;
  export: (name: string) => Promise<string>;
  import: (items: File[] | string[]) => Promise<Effect[]>;
  list: () => Promise<Effect[]>;
  save: (effect: Effect, originalName?: string) => Promise<Effect>;
  saveAudioTags: (input: { audioTags: string; name: string }) => Promise<Effect>;
  saveImageTags: (input: { imageTags: string; name: string }) => Promise<Effect>;
  uploadAudio: (input: { audioTags: string; name: string; paths: string[] }) => Promise<Effect>;
  uploadImages: (input: { imageTags: string; name: string; paths: string[] }) => Promise<Effect>;
  uploadImageAudio: (input: { index: number; name: string; path: string }) => Promise<Effect>;
}

export interface TemplatesPlatform {
  generate: (input: TemplateGenerateInput) => Promise<TemplateGenerationResult>;
  getPresets: () => Promise<UserPromptPresetLibrary>;
  getSession: () => Promise<TemplateLaunchSession | null>;
  list: () => Promise<TemplateSummary[]>;
  save: (template: TemplateSummary) => Promise<TemplateSummary>;
  savePresets: (library: UserPromptPresetLibrary) => Promise<UserPromptPresetLibrary>;
  saveSession: (session: TemplateLaunchSession) => Promise<TemplateLaunchSession>;
}

export interface ToolsPlatform {
  cropSprites: (
    input: { inputDir: string; outputDir?: string; ratio: number },
    options?: TaskProgressOptions<BatchToolResult>,
  ) => Promise<BatchToolResult>;
  generateSpritePrompts: (
    input: { characterName: string; count: number },
    options?: TaskProgressOptions<SpritePromptResult>,
  ) => Promise<SpritePromptResult>;
  generateSprites: (
    input: { characterName: string; outputDir?: string; prompts: string[]; referenceImage: string },
    options?: TaskProgressOptions<SpriteGenerationResult>,
  ) => Promise<SpriteGenerationResult>;
  removeSpriteBackground: (
    input: { inputDir: string; outputDir?: string },
    options?: TaskProgressOptions<BatchToolResult>,
  ) => Promise<BatchToolResult>;
}
