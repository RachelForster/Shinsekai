import type { CSSProperties } from "react";

import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";
import { normalizePlayerOptions } from "../../shared/playerCharacterOptions";
import type {
  ChatLaunchPayload,
  ChatSnapshot,
  InitialOutfitValue,
  MediaSelectionMode,
  MemoryMode,
  PlayerCharacterOptions,
  TemplateGenerateInput,
  TemplateLaunchSession,
  TemplateSummary,
} from "../../shared/platform/types";

export const templateVoiceLanguages = [
  { labelKey: "system.asr.langJa", value: "ja" },
  { labelKey: "system.asr.langEn", value: "en" },
  { labelKey: "system.asr.langZh", value: "zh" },
  { labelKey: "system.asr.langYue", value: "yue" },
] as const;

type CharacterChipStyle = CSSProperties & {
  "--template-character-color"?: string;
};

export interface TemplateFlowOptions {
  useCg: boolean;
  useChoice: boolean;
  useCot: boolean;
  useEffect: boolean;
  useNarration: boolean;
  useStat: boolean;
  useTranslation: boolean;
}

export interface TemplateRuntimeOptions {
  historyPath: string;
  initSpritePath: string;
  showInitialSprite?: boolean;
  maxDialogItems: number;
  maxSpeechChars: number;
  roomId: string;
  voiceLanguage: string;
}

export function getCharacterChipStyle(color: string): CharacterChipStyle {
  return {
    "--template-character-color": color.trim() || DEFAULT_CHARACTER_COLOR,
  };
}

export function composeTemplateContent(scenario: unknown, system: unknown) {
  return [String(scenario ?? "").trim(), String(system ?? "").trim()].filter(Boolean).join("\n\n");
}

export function buildDefaultTemplateScenario(selectedCharacters: string[], defaultScenario: string) {
  const names = selectedCharacters.map((name) => name.trim()).filter(Boolean);
  if (!names.length) {
    return "";
  }
  return defaultScenario;
}

export function createTemplateDraft(name: string): TemplateSummary {
  return {
    content: "",
    id: "",
    name,
    path: "",
    mediaSelectionMode: "indexed",
    scenario: "",
    system: "",
    updatedAt: "",
  };
}

export function normalizeTemplateSummary(template: TemplateSummary): TemplateSummary {
  const scenario = template.scenario ?? (template.system ? "" : (template.content ?? ""));
  const system = template.system ?? (template.scenario ? (template.content ?? "") : "");
  return {
    ...template,
    content: composeTemplateContent(scenario, system),
    mediaSelectionMode: template.mediaSelectionMode ?? "indexed",
    scenario,
    system,
  };
}

export function buildTemplateSummary(draft: TemplateSummary): TemplateSummary {
  const name = draft.name.trim();
  const scenario = String(draft.scenario ?? "");
  const system = String(draft.system ?? "");
  return {
    ...draft,
    content: composeTemplateContent(scenario, system),
    name,
    scenario,
    system,
  };
}

export function templateGenerationKey(
  input: Pick<
    TemplateGenerateInput,
    "characters" | "characterPromptMode" | "primaryCharacters" | "mediaSelectionMode"
  > &
    PlayerCharacterOptions,
): string {
  const player = normalizePlayerOptions(input);
  return `${input.characters.join("\n")}\n--${input.characterPromptMode ?? "pending"}\n${(input.primaryCharacters ?? []).join("\n")}\n--${input.mediaSelectionMode ?? "indexed"}\n--${player.playerCharacter}\n--${player.readPlayerSpeech}\n--${player.allowPlayerDialogue}`;
}

type TemplateGenerationOptions = PlayerCharacterOptions & {
  backgroundName: string;
  draft: TemplateSummary;
  effectNames?: string[];
  options: TemplateFlowOptions;
  runtime: Pick<TemplateRuntimeOptions, "maxDialogItems" | "maxSpeechChars" | "voiceLanguage">;
  selectedCharacters: string[];
  characterPromptMode?: "compact" | "full";
  primaryCharacters?: string[];
  mediaSelectionMode: MediaSelectionMode;
};

export function buildTemplateGenerateInput(input: TemplateGenerationOptions): TemplateGenerateInput {
  return {
    backgroundName: input.backgroundName,
    characterPromptMode: input.characterPromptMode,
    characters: input.selectedCharacters,
    effectNames: input.effectNames?.length ? input.effectNames : undefined,
    maxDialogItems: input.runtime.maxDialogItems,
    maxSpeechChars: input.runtime.maxSpeechChars,
    mediaSelectionMode: input.mediaSelectionMode,
    name: input.draft.name.trim(),
    primaryCharacters: input.primaryCharacters,
    ...normalizePlayerOptions(input),
    readPlayerSpeech: Boolean(input.playerCharacter && input.readPlayerSpeech),
    scenario: String(input.draft.scenario ?? ""),
    useCg: input.options.useCg,
    useChoice: input.options.useChoice,
    useCot: input.options.useCot,
    useEffect: input.options.useEffect,
    useNarration: input.options.useNarration,
    useStat: input.options.useStat,
    useTranslation: input.options.useTranslation,
    voiceLanguage: input.runtime.voiceLanguage,
  };
}

type TemplateSessionOptions = PlayerCharacterOptions & {
  autoOutfitSwitch?: boolean;
  backgroundName: string;
  draft: TemplateSummary;
  effectNames?: string[];
  initialOutfits?: Record<string, InitialOutfitValue>;
  memoryMode?: MemoryMode;
  mobileAccessEnabled: boolean;
  options: TemplateFlowOptions;
  runtime: TemplateRuntimeOptions;
  selectedCharacters: string[];
  characterPromptMode?: "compact" | "full";
  primaryCharacters?: string[];
  mediaSelectionMode: MediaSelectionMode;
  selectedTemplateId: string;
};

export function buildTemplateLaunchSession(input: TemplateSessionOptions): TemplateLaunchSession {
  const initialOutfits =
    input.initialOutfits && Object.keys(input.initialOutfits).length > 0 ? { ...input.initialOutfits } : undefined;
  return {
    ...(input.autoOutfitSwitch !== undefined ? { autoOutfitSwitch: input.autoOutfitSwitch } : {}),
    background: input.backgroundName,
    characterPromptMode: input.characterPromptMode,
    enableMobileAccess: input.mobileAccessEnabled,
    effectNames: input.effectNames ?? [],
    filenameStub: input.draft.name.trim(),
    historyPath: input.runtime.historyPath.trim(),
    ...(initialOutfits ? { initialOutfits } : {}),
    initSpritePath: input.runtime.initSpritePath.trim(),
    showInitialSprite: input.runtime.showInitialSprite ?? true,
    maxDialogItems: input.runtime.maxDialogItems,
    maxSpeechChars: input.runtime.maxSpeechChars,
    mediaSelectionMode: input.mediaSelectionMode,
    ...(input.memoryMode ? { memoryMode: input.memoryMode } : {}),
    roomId: input.runtime.roomId.trim(),
    scenario: String(input.draft.scenario ?? ""),
    primaryCharacters: input.primaryCharacters,
    ...normalizePlayerOptions(input),
    selectedCharacters: input.selectedCharacters,
    system: String(input.draft.system ?? ""),
    templateFileDropdown: input.selectedTemplateId,
    useCg: input.options.useCg,
    useChoice: input.options.useChoice,
    useCot: input.options.useCot,
    useEffect: input.options.useEffect,
    useNarration: input.options.useNarration,
    useStat: input.options.useStat,
    useTranslation: input.options.useTranslation,
    voiceLanguage: input.runtime.voiceLanguage,
  };
}

export function buildChatLaunchPayload(input: {
  autoOutfitSwitch?: boolean;
  backgroundName: string;
  effectNames?: string[];
  initialOutfits?: Record<string, InitialOutfitValue>;
  memoryMode?: MemoryMode;
  mobileAccessEnabled: boolean;
  resetHistory: boolean;
  runtime: Pick<TemplateRuntimeOptions, "historyPath" | "initSpritePath" | "showInitialSprite" | "roomId">;
  selectedCharacters: string[];
  template: TemplateSummary;
  useCg: boolean;
  mediaSelectionMode: MediaSelectionMode;
}): ChatLaunchPayload {
  const initialOutfits =
    input.initialOutfits && Object.keys(input.initialOutfits).length > 0 ? { ...input.initialOutfits } : undefined;
  return {
    ...(input.autoOutfitSwitch !== undefined ? { autoOutfitSwitch: input.autoOutfitSwitch } : {}),
    backgroundName: input.backgroundName,
    characters: input.selectedCharacters,
    enableMobileAccess: input.mobileAccessEnabled,
    effectNames: input.effectNames?.length ? input.effectNames : undefined,
    historyPath: input.runtime.historyPath.trim(),
    ...(initialOutfits ? { initialOutfits } : {}),
    initSpritePath: input.runtime.initSpritePath.trim(),
    showInitialSprite: input.runtime.showInitialSprite ?? true,
    mediaSelectionMode: input.mediaSelectionMode,
    ...(input.memoryMode ? { memoryMode: input.memoryMode } : {}),
    resetHistory: input.resetHistory,
    roomId: input.runtime.roomId.trim(),
    scenario: String(input.template.scenario ?? ""),
    system: String(input.template.system ?? ""),
    templateId: input.template.id,
    templateName: input.template.name,
    useCg: input.useCg,
  };
}

export function synchronizeChatLaunchPayloadWithSession(
  payload: ChatLaunchPayload,
  session: TemplateLaunchSession,
): ChatLaunchPayload {
  const effectNames = Array.isArray(session.effectNames) ? session.effectNames : [];
  const initialOutfits =
    session.initialOutfits && Object.keys(session.initialOutfits).length > 0
      ? { ...session.initialOutfits }
      : undefined;
  return {
    ...payload,
    ...(session.autoOutfitSwitch !== undefined ? { autoOutfitSwitch: session.autoOutfitSwitch } : {}),
    backgroundName: session.background,
    characterPromptMode: session.characterPromptMode,
    characters: session.selectedCharacters,
    primaryCharacters: session.primaryCharacters,
    ...normalizePlayerOptions(session),
    enableMobileAccess: session.enableMobileAccess,
    effectNames: effectNames.length ? effectNames : undefined,
    historyPath: session.historyPath.trim(),
    ...(initialOutfits ? { initialOutfits } : {}),
    initSpritePath: session.initSpritePath.trim(),
    showInitialSprite: session.showInitialSprite ?? true,
    mediaSelectionMode: session.mediaSelectionMode ?? "indexed",
    ...(session.memoryMode ? { memoryMode: session.memoryMode } : {}),
    roomId: session.roomId.trim(),
    scenario: session.scenario,
    system: session.system,
    templateId: session.templateFileDropdown,
    templateName: session.filenameStub,
    useCg: session.useCg,
  };
}

export function synchronizeTemplateLaunchSessionWithSnapshot(
  session: TemplateLaunchSession,
  snapshot: ChatSnapshot,
): TemplateLaunchSession {
  if (snapshot.runtimeDependencyError) {
    return session;
  }
  const confirmedHistoryPath = snapshot.historyPath?.trim();
  if (!confirmedHistoryPath || confirmedHistoryPath === session.historyPath) {
    return session;
  }
  return { ...session, historyPath: confirmedHistoryPath };
}
