import type { CSSProperties } from "react";

import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";
import { normalizePlayerOptions } from "../../shared/playerCharacterOptions";
import type {
  AppliedUserPromptPreset,
  ChatLaunchPayload,
  ChatSnapshot,
  DialogFormatOption,
  DialogOutputFormatId,
  InitialOutfitValue,
  MediaSelectionMode,
  MemoryMode,
  PlayerCharacterOptions,
  TemplateGenerateInput,
  TemplateLaunchSession,
  TemplateSummary,
} from "../../shared/platform/types";

export const DEFAULT_NEW_OUTPUT_FORMAT: DialogOutputFormatId = "xml_v1";
export const LEGACY_OUTPUT_FORMAT: DialogOutputFormatId = "json_v1";

export const FALLBACK_DIALOG_FORMATS: DialogFormatOption[] = [
  { id: "xml_v1", label: "XML / HTML Tags", builtin: true },
  { id: "renpy_v1", label: "Ren'Py Script DSL", builtin: true },
  { id: "json_v1", label: "JSON", builtin: true },
];

export function resolveSupportedOutputFormat(
  candidate: DialogOutputFormatId | null | undefined,
  dialogFormats: readonly DialogFormatOption[] | undefined,
  fallback: DialogOutputFormatId = LEGACY_OUTPUT_FORMAT,
): DialogOutputFormatId {
  const preferred = candidate || fallback;
  if (!dialogFormats?.length) {
    return preferred;
  }
  if (dialogFormats.some((item) => item.id === preferred)) {
    return preferred;
  }
  if (dialogFormats.some((item) => item.id === fallback)) {
    return fallback;
  }
  if (dialogFormats.some((item) => item.id === DEFAULT_NEW_OUTPUT_FORMAT)) {
    return DEFAULT_NEW_OUTPUT_FORMAT;
  }
  return dialogFormats[0].id;
}

export const templateVoiceLanguages = [
  { labelKey: "system.asr.langAuto", value: "auto" },
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
    appliedPresets: [],
    baseScenario: "",
    content: "",
    id: "",
    name,
    outputFormat: DEFAULT_NEW_OUTPUT_FORMAT,
    path: "",
    mediaSelectionMode: "indexed",
    scenario: "",
    selectedPresetIds: [],
    system: "",
    updatedAt: "",
  };
}

export function normalizeTemplateSummary(template: TemplateSummary): TemplateSummary {
  const scenario = template.scenario ?? (template.system ? "" : (template.content ?? ""));
  const baseScenario = template.baseScenario ?? scenario;
  const selectedPresetIds = Array.isArray(template.selectedPresetIds) ? [...template.selectedPresetIds] : [];
  const appliedPresets = Array.isArray(template.appliedPresets)
    ? template.appliedPresets.map((item) => ({ ...item }))
    : [];
  const system = template.system ?? (template.scenario ? (template.content ?? "") : "");
  return {
    ...template,
    appliedPresets,
    baseScenario,
    content: composeTemplateContent(scenario, system),
    mediaSelectionMode: template.mediaSelectionMode ?? "indexed",
    ...(template.outputFormat ? { outputFormat: template.outputFormat } : {}),
    scenario,
    selectedPresetIds,
    system,
  };
}

export function buildTemplateSummary(draft: TemplateSummary): TemplateSummary {
  const name = draft.name.trim();
  const scenario = String(draft.scenario ?? "");
  const baseScenario = String(draft.baseScenario ?? scenario);
  const selectedPresetIds = Array.isArray(draft.selectedPresetIds) ? [...draft.selectedPresetIds] : [];
  const appliedPresets = Array.isArray(draft.appliedPresets) ? draft.appliedPresets.map((item) => ({ ...item })) : [];
  const system = String(draft.system ?? "");
  return {
    ...draft,
    appliedPresets,
    baseScenario,
    content: composeTemplateContent(scenario, system),
    name,
    scenario,
    selectedPresetIds,
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
  outputFormat?: DialogOutputFormatId;
  runtime: Pick<TemplateRuntimeOptions, "maxDialogItems" | "maxSpeechChars" | "voiceLanguage">;
  selectedCharacters: string[];
  characterPromptMode?: "compact" | "full";
  primaryCharacters?: string[];
  mediaSelectionMode: MediaSelectionMode;
};

export function buildTemplateGenerateInput(input: TemplateGenerationOptions): TemplateGenerateInput {
  const outputFormat = input.outputFormat ?? input.draft.outputFormat;
  return {
    backgroundName: input.backgroundName,
    characterPromptMode: input.characterPromptMode,
    characters: input.selectedCharacters,
    effectNames: input.effectNames?.length ? input.effectNames : undefined,
    maxDialogItems: input.runtime.maxDialogItems,
    maxSpeechChars: input.runtime.maxSpeechChars,
    mediaSelectionMode: input.mediaSelectionMode,
    name: input.draft.name.trim(),
    ...(outputFormat ? { outputFormat } : {}),
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
  appliedPresets?: AppliedUserPromptPreset[];
  autoOutfitSwitch?: boolean;
  backgroundName: string;
  baseScenario?: string;
  behaviorConfig?: Record<string, unknown>;
  behaviorId?: string;
  draft: TemplateSummary;
  effectNames?: string[];
  initialOutfits?: Record<string, InitialOutfitValue>;
  memoryMode?: MemoryMode;
  mobileAccessEnabled: boolean;
  options: TemplateFlowOptions;
  outputFormat?: DialogOutputFormatId;
  runtime: TemplateRuntimeOptions;
  selectedCharacters: string[];
  selectedPresetIds?: string[];
  characterPromptMode?: "compact" | "full";
  primaryCharacters?: string[];
  mediaSelectionMode: MediaSelectionMode;
  selectedTemplateId: string;
  systemManuallyEdited?: boolean;
};

export function buildTemplateLaunchSession(input: TemplateSessionOptions): TemplateLaunchSession {
  const initialOutfits =
    input.initialOutfits && Object.keys(input.initialOutfits).length > 0 ? { ...input.initialOutfits } : undefined;
  const behaviorId = String(input.behaviorId ?? "").trim();
  const behaviorConfig =
    behaviorId && input.behaviorConfig && Object.keys(input.behaviorConfig).length > 0
      ? { ...input.behaviorConfig }
      : undefined;
  const selectedPresetIds = input.selectedPresetIds ?? input.draft.selectedPresetIds ?? [];
  const appliedPresets = input.appliedPresets ?? input.draft.appliedPresets ?? [];
  const baseScenario = input.baseScenario ?? input.draft.baseScenario ?? String(input.draft.scenario ?? "");
  const outputFormat = input.outputFormat ?? input.draft.outputFormat;
  return {
    ...(input.autoOutfitSwitch !== undefined ? { autoOutfitSwitch: input.autoOutfitSwitch } : {}),
    background: input.backgroundName,
    ...(behaviorId ? { behaviorId } : {}),
    ...(behaviorConfig ? { behaviorConfig } : {}),
    ...(selectedPresetIds.length || baseScenario !== String(input.draft.scenario ?? "")
      ? {
          baseScenario,
          selectedPresetIds: [...selectedPresetIds],
          appliedPresets: appliedPresets.map((item) => ({ ...item })),
        }
      : {}),
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
    ...(outputFormat ? { outputFormat } : {}),
    roomId: input.runtime.roomId.trim(),
    scenario: String(input.draft.scenario ?? ""),
    primaryCharacters: input.primaryCharacters,
    ...normalizePlayerOptions(input),
    selectedCharacters: input.selectedCharacters,
    system: String(input.draft.system ?? ""),
    ...(input.systemManuallyEdited !== undefined ? { systemManuallyEdited: input.systemManuallyEdited } : {}),
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
  behaviorConfig?: Record<string, unknown>;
  behaviorId?: string;
  effectNames?: string[];
  initialOutfits?: Record<string, InitialOutfitValue>;
  memoryMode?: MemoryMode;
  mobileAccessEnabled: boolean;
  outputFormat?: DialogOutputFormatId;
  resetHistory: boolean;
  runtime: Pick<TemplateRuntimeOptions, "historyPath" | "initSpritePath" | "showInitialSprite" | "roomId">;
  selectedCharacters: string[];
  template: TemplateSummary;
  useCg: boolean;
  mediaSelectionMode: MediaSelectionMode;
}): ChatLaunchPayload {
  const initialOutfits =
    input.initialOutfits && Object.keys(input.initialOutfits).length > 0 ? { ...input.initialOutfits } : undefined;
  const behaviorId = String(input.behaviorId ?? "").trim();
  const behaviorConfig =
    behaviorId && input.behaviorConfig && Object.keys(input.behaviorConfig).length > 0
      ? { ...input.behaviorConfig }
      : undefined;
  const outputFormat = input.outputFormat ?? input.template.outputFormat;
  return {
    ...(input.autoOutfitSwitch !== undefined ? { autoOutfitSwitch: input.autoOutfitSwitch } : {}),
    backgroundName: input.backgroundName,
    ...(behaviorId ? { behaviorId } : {}),
    ...(behaviorConfig ? { behaviorConfig } : {}),
    characters: input.selectedCharacters,
    enableMobileAccess: input.mobileAccessEnabled,
    effectNames: input.effectNames?.length ? input.effectNames : undefined,
    historyPath: input.runtime.historyPath.trim(),
    ...(initialOutfits ? { initialOutfits } : {}),
    initSpritePath: input.runtime.initSpritePath.trim(),
    showInitialSprite: input.runtime.showInitialSprite ?? true,
    mediaSelectionMode: input.mediaSelectionMode,
    ...(input.memoryMode ? { memoryMode: input.memoryMode } : {}),
    ...(outputFormat ? { outputFormat } : {}),
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
  const behaviorId = String(session.behaviorId ?? "").trim();
  const behaviorConfig =
    behaviorId && session.behaviorConfig && Object.keys(session.behaviorConfig).length > 0
      ? { ...session.behaviorConfig }
      : undefined;
  const initialOutfits =
    session.initialOutfits && Object.keys(session.initialOutfits).length > 0
      ? { ...session.initialOutfits }
      : undefined;
  return {
    ...payload,
    ...(session.autoOutfitSwitch !== undefined ? { autoOutfitSwitch: session.autoOutfitSwitch } : {}),
    backgroundName: session.background,
    ...(behaviorId ? { behaviorId } : {}),
    ...(behaviorConfig ? { behaviorConfig } : {}),
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
    ...(session.outputFormat ? { outputFormat: session.outputFormat } : {}),
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
