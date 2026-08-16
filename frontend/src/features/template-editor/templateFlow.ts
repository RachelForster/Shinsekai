import type { CSSProperties } from "react";

import { DEFAULT_CHARACTER_COLOR, TRANSPARENT_BACKGROUND_NAME } from "../../shared/constants";
import type {
  ChatLaunchPayload,
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

export function buildTemplateGenerateInput(input: {
  backgroundName: string;
  draft: TemplateSummary;
  effectNames?: string[];
  options: TemplateFlowOptions;
  runtime: Pick<TemplateRuntimeOptions, "maxDialogItems" | "maxSpeechChars" | "voiceLanguage">;
  selectedCharacters: string[];
}): TemplateGenerateInput {
  return {
    backgroundName: input.backgroundName,
    characters: input.selectedCharacters,
    effectNames: input.effectNames?.length ? input.effectNames : undefined,
    maxDialogItems: input.runtime.maxDialogItems,
    maxSpeechChars: input.runtime.maxSpeechChars,
    name: input.draft.name.trim(),
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

export function buildTemplateLaunchSession(input: {
  backgroundName: string;
  draft: TemplateSummary;
  effectNames?: string[];
  mobileAccessEnabled: boolean;
  options: TemplateFlowOptions;
  runtime: TemplateRuntimeOptions;
  selectedCharacters: string[];
  selectedTemplateId: string;
  storyId?: string;
}): TemplateLaunchSession {
  return {
    background: input.backgroundName,
    enableMobileAccess: input.mobileAccessEnabled,
    effectNames: input.effectNames ?? [],
    filenameStub: input.draft.name.trim(),
    historyPath: input.runtime.historyPath.trim(),
    initSpritePath: input.runtime.initSpritePath.trim(),
    maxDialogItems: input.runtime.maxDialogItems,
    maxSpeechChars: input.runtime.maxSpeechChars,
    roomId: input.runtime.roomId.trim(),
    scenario: String(input.draft.scenario ?? ""),
    selectedCharacters: input.selectedCharacters,
    storyId: input.storyId?.trim() || undefined,
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
  backgroundName: string;
  effectNames?: string[];
  mobileAccessEnabled: boolean;
  resetHistory: boolean;
  runtime: Pick<TemplateRuntimeOptions, "historyPath" | "initSpritePath" | "roomId">;
  selectedCharacters: string[];
  template: TemplateSummary;
  useCg: boolean;
  storyId?: string;
}): ChatLaunchPayload {
  return {
    backgroundName: input.backgroundName,
    characters: input.selectedCharacters,
    enableMobileAccess: input.mobileAccessEnabled,
    effectNames: input.effectNames?.length ? input.effectNames : undefined,
    historyPath: input.runtime.historyPath.trim(),
    initSpritePath: input.runtime.initSpritePath.trim(),
    resetHistory: input.resetHistory,
    roomId: input.runtime.roomId.trim(),
    scenario: String(input.template.scenario ?? ""),
    storyId: input.storyId?.trim() || undefined,
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
  const storyId = String(payload.storyId || session.storyId || "").trim();
  if (storyId) {
    return {
      ...payload,
      backgroundName: TRANSPARENT_BACKGROUND_NAME,
      characters: [],
      enableMobileAccess: Boolean(session.enableMobileAccess ?? payload.enableMobileAccess),
      effectNames: undefined,
      historyPath: "",
      initSpritePath: "",
      roomId: String(session.roomId || payload.roomId || "").trim(),
      scenario: "",
      storyId,
      system: "",
      templateId: session.templateFileDropdown || payload.templateId,
      templateName: session.filenameStub || payload.templateName,
      useCg: false,
    };
  }
  const effectNames = Array.isArray(session.effectNames) ? session.effectNames : [];
  return {
    ...payload,
    backgroundName: session.background,
    characters: session.selectedCharacters,
    enableMobileAccess: session.enableMobileAccess,
    effectNames: effectNames.length ? effectNames : undefined,
    historyPath: session.historyPath.trim(),
    initSpritePath: session.initSpritePath.trim(),
    roomId: session.roomId.trim(),
    scenario: session.scenario,
    storyId: undefined,
    system: session.system,
    templateId: session.templateFileDropdown,
    templateName: session.filenameStub,
    useCg: session.useCg,
  };
}
