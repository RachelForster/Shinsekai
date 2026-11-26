import type { Dispatch, SetStateAction } from "react";

import type { TemplateSummary, UserPromptPresetLibrary } from "../../entities/template/repository";
import type {
  AppliedUserPromptPreset,
  Character,
  CharacterPromptMode,
  ChatSnapshot,
  DialogFormatOption,
  DialogOutputFormatId,
  Effect,
  MediaSelectionMode,
  MemoryMode,
  MobileAccessInfo,
  TaskSnapshot,
  UserPromptPreset,
} from "../../shared/platform/types";
import { DEFAULT_SPRITE_GROUP } from "../../shared/constants";
import type { ChatInitializationService } from "../chat-startup/useChatInitialization";
import type { CharacterConfigCommit } from "./CharacterConfigDialog";
import type { SystemPromptCommit, SystemPromptRulesDraft } from "./SystemPromptDialog";
import type { UserPromptCommit } from "./UserPromptPresetsDialog";

export type TemplateSectionSlot = "main" | "sidebar";

export const MAX_VISIBLE_PRESET_CHIPS = 6;

export interface TemplateEditorPageProps {
  conversationId?: string;
  conversationTitle?: string;
  createOnly?: boolean;
  initializationService?: ChatInitializationService;
  onApplied?: (snapshot: ChatSnapshot) => void;
  onLaunchStarted?: () => void;
  onPendingChange?: (pending: boolean) => void;
}

export function characterOutfitGroups(character: {
  default_sprite_group?: string | null;
  sprite_groups?: string[] | null;
  sprites?: Array<{ group?: string | null }> | null;
}): string[] {
  const seen = new Set<string>([DEFAULT_SPRITE_GROUP]);
  const ordered = [DEFAULT_SPRITE_GROUP];
  const push = (raw?: string | null) => {
    const trimmed = String(raw ?? "").trim() || DEFAULT_SPRITE_GROUP;
    if (!seen.has(trimmed)) {
      seen.add(trimmed);
      ordered.push(trimmed);
    }
  };
  for (const group of character.sprite_groups ?? []) {
    push(group);
  }
  if (character.default_sprite_group) {
    push(character.default_sprite_group);
  }
  for (const sprite of character.sprites ?? []) {
    if (sprite.group) {
      push(sprite.group);
    }
  }
  return ordered;
}

export function buildSystemSyncKey(input: {
  characterKey: string;
  backgroundName: string;
  voiceLanguage: string;
  useCg: boolean;
  useEffect: boolean;
  useTranslation: boolean;
  useCot: boolean;
  useChoice: boolean;
  useNarration: boolean;
  useStat: boolean;
  maxSpeechChars: number;
  maxDialogItems: number;
  outputFormat?: DialogOutputFormatId;
}) {
  return [
    input.characterKey,
    input.backgroundName,
    input.voiceLanguage,
    input.useCg,
    input.useEffect,
    input.useTranslation,
    input.useCot,
    input.useChoice,
    input.useNarration,
    input.useStat,
    input.maxSpeechChars,
    input.maxDialogItems,
    input.outputFormat ?? "",
  ].join("\n::");
}

export type ResolvedPresetView = UserPromptPreset & { isDeleted?: boolean };

export interface TemplateEditorContext {
  allowPlayerDialogue: boolean;
  appliedPresetsSnapshot: AppliedUserPromptPreset[];
  autoOutfitSwitch: boolean;
  backgroundOptions: string[];
  baseScenario: string;
  characterByName: Map<string, Character>;
  characterDialogError: string;
  characterDialogOpen: boolean;
  characterPromptMode: CharacterPromptMode | undefined;
  characters: Character[];
  closeInitialization: () => void;
  closeMobileAccess: () => void;
  confirmCharacterConfig: (next: CharacterConfigCommit) => Promise<void>;
  confirmPrimaryCharacters: (nextPrimaryCharacters: string[]) => Promise<void>;
  conversationId?: string;
  createOnly: boolean;
  dialogFormats: DialogFormatOption[];
  draft: TemplateSummary;
  effectivePlayerCharacter: string;
  effects: Effect[];
  enabledRulesCount: number;
  ensureBriefsPending: boolean;
  failedQuery: { error: unknown; refetch: () => Promise<unknown> } | undefined;
  generatePending: boolean;
  handleConfirmSystemPrompt: (commit: SystemPromptCommit) => void;
  handleConfirmUserPrompt: (commit: UserPromptCommit) => void;
  handleLaunch: (resetHistory: boolean) => void;
  handleRegenerateFromDialog: (rules: SystemPromptRulesDraft, options: { silent: boolean }) => Promise<string | null>;
  handleTemplateSelect: (nextId: string) => void;
  handleVoiceLanguageChange: (nextLanguage: string) => void;
  hiddenPresetCount: number;
  historyPath: string;
  initializationError: string | null;
  initializationOpen: boolean;
  initializationPending: boolean;
  initializationServiceProvided: boolean;
  initializationTask: TaskSnapshot<ChatSnapshot> | null;
  initialOutfits: Record<string, string>;
  initSpritePath: string;
  isCreating: boolean;
  isLoading: boolean;
  launchPending: boolean;
  maxDialogItems: number;
  maxSpeechChars: number;
  mediaSelectionMode: MediaSelectionMode;
  memoryMode: MemoryMode;
  mobileAccessInfo: MobileAccessInfo | null;
  nameError: string;
  openCharacterDialog: () => void;
  openLocalChatFromMobile: () => void;
  outputFormat: DialogOutputFormatId;
  playerCharacter: string;
  presetsLibrary: UserPromptPresetLibrary;
  presetsLibraryError: boolean;
  presetsLibraryPending: boolean;
  presetsLibraryReady: boolean;
  primaryCharacterDialogOpen: boolean;
  primaryCharacters: string[];
  quickRestartOpen: boolean;
  readPlayerSpeech: boolean;
  resolvedSelectedPresets: ResolvedPresetView[];
  restoreDefaultScenario: () => void;
  retryPresetsLibrary: () => void;
  roleSummaryText: string;
  runtimeClosing: boolean;
  runtimeLaunchDisabled: boolean;
  saveLibraryPresets: (nextLibrary: UserPromptPresetLibrary) => Promise<UserPromptPresetLibrary>;
  savePending: boolean;
  savePresetsPending: boolean;
  saveTemplate: () => void;
  scenarioStatusKey: "template.bar.scenarioEmpty" | "template.bar.scenarioDefault" | "template.bar.scenarioCustom";
  selectedBackground: string;
  selectedCharacterRecords: Character[];
  selectedCharacters: string[];
  selectedEffectNames: Set<string>;
  sessionDraftActive: boolean;
  sessionRestored: boolean;
  setAutoOutfitSwitch: Dispatch<SetStateAction<boolean>>;
  setCharacterDialogOpen: Dispatch<SetStateAction<boolean>>;
  setHistoryPath: Dispatch<SetStateAction<string>>;
  setInitialOutfits: Dispatch<SetStateAction<Record<string, string>>>;
  setInitSpritePath: Dispatch<SetStateAction<string>>;
  setMemoryMode: Dispatch<SetStateAction<MemoryMode>>;
  setNameError: Dispatch<SetStateAction<string>>;
  setQuickRestartOpen: Dispatch<SetStateAction<boolean>>;
  setSelectedBackground: Dispatch<SetStateAction<string>>;
  setSessionDraftActive: Dispatch<SetStateAction<boolean>>;
  setShowInitialSprite: Dispatch<SetStateAction<boolean>>;
  setSystemPromptDialogOpen: Dispatch<SetStateAction<boolean>>;
  setUseCg: Dispatch<SetStateAction<boolean>>;
  setUserPromptDialogOpen: Dispatch<SetStateAction<boolean>>;
  showInitialSprite: boolean;
  showRoleSummary: boolean;
  systemConfigStale: boolean;
  systemManuallyEdited: boolean;
  systemPromptDialogOpen: boolean;
  systemStatusPill: { className: string; label: string };
  templateSelectValue: string;
  templates: TemplateSummary[];
  toggleEffect: (name: string, checked: boolean) => void;
  updateDraft: (patch: Partial<TemplateSummary>) => void;
  useAllCharactersAsPrimary: () => void;
  useCg: boolean;
  useChoice: boolean;
  useCot: boolean;
  useEffectPrompt: boolean;
  useNarration: boolean;
  userPromptDialogOpen: boolean;
  useStat: boolean;
  useTranslation: boolean;
  visiblePresetChips: ResolvedPresetView[];
  voiceLanguage: string;
}
