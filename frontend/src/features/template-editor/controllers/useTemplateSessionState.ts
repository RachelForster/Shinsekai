import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { backgroundsQueryKey, listBackgrounds } from "../../../entities/background/repository";
import { charactersQueryKey, listCharacters } from "../../../entities/character/repository";
import { conversationsQueryKey, getConversationSession } from "../../../entities/chat/repository";
import { configQueryKey, getAppConfig } from "../../../entities/config/repository";
import { effectsQueryKey, listEffects } from "../../../entities/effect/repository";
import {
  dialogFormatsQueryKey,
  getTemplateSession,
  getUserPromptPresets,
  listDialogFormats,
  listTemplates,
  templatesQueryKey,
  userPromptPresetsQueryKey,
  type DialogFormatOption,
  type DialogOutputFormatId,
  type TemplateSummary,
} from "../../../entities/template/repository";
import { TRANSPARENT_BACKGROUND_NAME } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import { DEFAULT_PLAYER_OPTIONS } from "../../../shared/playerCharacterOptions";
import type { CharacterPromptMode, MediaSelectionMode, MemoryMode } from "../../../shared/platform/types";
import { useMobileAccessPreference } from "../../mobile-access/useMobileAccessPreference";
import { useSemanticMediaController } from "../SemanticMediaSwitch";
import { buildSystemSyncKey } from "../templateContext";
import {
  buildDefaultTemplateScenario,
  composeTemplateContent,
  createTemplateDraft,
  DEFAULT_NEW_OUTPUT_FORMAT,
  templateGenerationKey,
} from "../templateFlow";
import {
  composeScenarioWithPresets,
  normalizeUserPromptPresetLibrary,
  resolveSelectedPresets,
  toAppliedPresets,
} from "../userPromptPresets";
import { useTemplateRestoreEffects } from "./useTemplateRestoreEffects";

interface UseTemplateSessionStateOptions {
  conversationId?: string;
  createOnly: boolean;
}

const FALLBACK_DIALOG_FORMATS: DialogFormatOption[] = [
  { id: "xml_v1", label: "XML / HTML Tags", builtin: true },
  { id: "json_v1", label: "JSON", builtin: true },
];

export function useTemplateSessionState({ conversationId, createOnly }: UseTemplateSessionStateOptions) {
  const { t } = useI18n();
  const dialogFormatsQuery = useQuery({ queryFn: listDialogFormats, queryKey: dialogFormatsQueryKey });
  const templatesQuery = useQuery({ queryFn: listTemplates, queryKey: templatesQueryKey });
  const presetsQuery = useQuery({ queryFn: getUserPromptPresets, queryKey: userPromptPresetsQueryKey });
  const sessionQuery = useQuery({
    queryFn: () => (conversationId ? getConversationSession(conversationId) : getTemplateSession()),
    queryKey: conversationId
      ? [...conversationsQueryKey, conversationId, "settings"]
      : [...templatesQueryKey, "session"],
  });
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const backgroundsQuery = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });
  const effectsQuery = useQuery({ queryFn: listEffects, queryKey: effectsQueryKey });

  const templates = templatesQuery.data ?? [];
  const dialogFormatsLoaded = Boolean(dialogFormatsQuery.data?.length);
  const dialogFormats = dialogFormatsLoaded ? dialogFormatsQuery.data! : FALLBACK_DIALOG_FORMATS;
  const isLoading = templatesQuery.isLoading;
  const launchSession = sessionQuery.data;
  const sessionFetched = sessionQuery.isFetched;
  const appConfig = configQuery.data;
  const characters = charactersQuery.data ?? [];
  const backgrounds = backgroundsQuery.data ?? [];
  const effects = Array.isArray(effectsQuery.data) ? effectsQuery.data : [];
  const presetsLibrary = useMemo(() => normalizeUserPromptPresetLibrary(presetsQuery.data), [presetsQuery.data]);
  const presetsLibraryReady = presetsQuery.isSuccess;

  const [selectedId, setSelectedId] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [sessionDraftActive, setSessionDraftActive] = useState(false);
  const [sessionRestored, setSessionRestored] = useState(false);
  const [draft, setDraft] = useState<TemplateSummary>(() => createTemplateDraft(t("template.defaultName")));
  const [nameError, setNameError] = useState("");
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>([]);
  const [characterPromptMode, setCharacterPromptMode] = useState<CharacterPromptMode>();
  const [primaryCharacters, setPrimaryCharacters] = useState<string[]>([]);
  const [playerCharacter, setPlayerCharacter] = useState(DEFAULT_PLAYER_OPTIONS.playerCharacter);
  const [readPlayerSpeech, setReadPlayerSpeech] = useState(DEFAULT_PLAYER_OPTIONS.readPlayerSpeech);
  const [allowPlayerDialogue, setAllowPlayerDialogue] = useState(DEFAULT_PLAYER_OPTIONS.allowPlayerDialogue);
  const effectivePlayerCharacter = selectedCharacters.includes(playerCharacter) ? playerCharacter : "";
  const playerOptions = { playerCharacter: effectivePlayerCharacter, readPlayerSpeech, allowPlayerDialogue };
  const templatePlayerOptions = {
    ...playerOptions,
    readPlayerSpeech: Boolean(effectivePlayerCharacter && readPlayerSpeech),
  };

  const [mediaSelectionMode, setMediaSelectionMode] = useState<MediaSelectionMode>("indexed");
  const [outputFormat, setOutputFormat] = useState<DialogOutputFormatId>(DEFAULT_NEW_OUTPUT_FORMAT);
  const [primaryCharacterDialogOpen, setPrimaryCharacterDialogOpen] = useState(false);
  const [characterDialogOpen, setCharacterDialogOpen] = useState(false);
  const [userPromptDialogOpen, setUserPromptDialogOpen] = useState(false);
  const [systemPromptDialogOpen, setSystemPromptDialogOpen] = useState(false);
  const [characterDialogError, setCharacterDialogError] = useState("");
  const [launchReadyAfterRoleGeneration, setLaunchReadyAfterRoleGeneration] = useState<boolean | null>(null);

  const [selectedBackground, setSelectedBackground] = useState(TRANSPARENT_BACKGROUND_NAME);
  const [selectedEffects, setSelectedEffects] = useState<string[]>([]);
  const [voiceLanguage, setVoiceLanguage] = useState("ja");
  const [useEffectPrompt, setUseEffectPrompt] = useState(true);
  const [useTranslation, setUseTranslation] = useState(true);
  const [useCg, setUseCg] = useState(false);
  const [useCot, setUseCot] = useState(false);
  const [useChoice, setUseChoice] = useState(true);
  const [useNarration, setUseNarration] = useState(true);
  const [useStat, setUseStat] = useState(true);
  const [mobileAccessEnabled] = useMobileAccessPreference();
  const [maxSpeechChars, setMaxSpeechChars] = useState(0);
  const [maxDialogItems, setMaxDialogItems] = useState(0);
  const [initSpritePath, setInitSpritePath] = useState("");
  const [showInitialSprite, setShowInitialSprite] = useState(true);
  const [memoryMode, setMemoryMode] = useState<MemoryMode>("isolated");
  const [autoOutfitSwitch, setAutoOutfitSwitch] = useState(true);
  const [initialOutfits, setInitialOutfits] = useState<Record<string, string>>({});
  const [historyPath, setHistoryPath] = useState("");
  const [roomId, setRoomId] = useState("");
  const [systemManuallyEdited, setSystemManuallyEdited] = useState(false);
  const [manualBaseKey, setManualBaseKey] = useState("");

  const autoGenerateReadyRef = useRef(false);
  const lastAutoGeneratedKeyRef = useRef("");
  const lastAutoScenarioRef = useRef("");
  const suppressNextAutoGenerateRef = useRef(false);
  const deferredLaunchRef = useRef<boolean | null>(null);
  const restoredSessionBackgroundRef = useRef<string | null>(null);

  // Keep mem0 validation active on restore even before opening SystemPromptDialog.
  useSemanticMediaController({
    checked: mediaSelectionMode === "semantic",
    onChange: (enabled) => {
      const mode: MediaSelectionMode = enabled ? "semantic" : "indexed";
      setMediaSelectionMode(mode);
      setDraft((current) => ({ ...current, mediaSelectionMode: mode }));
    },
  });

  const selected = useMemo(
    () => (isCreating ? undefined : (templates.find((template) => template.id === selectedId) ?? templates[0])),
    [isCreating, selectedId, templates],
  );
  const backgroundOptions = useMemo(() => {
    const names = backgrounds.map((background) => background.name);
    return names.includes(TRANSPARENT_BACKGROUND_NAME) ? names : [...names, TRANSPARENT_BACKGROUND_NAME];
  }, [backgrounds]);
  const selectedCharacterNames = useMemo(() => new Set(selectedCharacters), [selectedCharacters]);
  const selectedCharacterRecords = useMemo(
    () => characters.filter((character) => selectedCharacterNames.has(character.name)),
    [characters, selectedCharacterNames],
  );
  const characterByName = useMemo(
    () => new Map(characters.map((character) => [character.name, character])),
    [characters],
  );
  const selectedEffectNames = useMemo(() => new Set(selectedEffects), [selectedEffects]);
  const failedQueryRaw = [
    templatesQuery,
    presetsQuery,
    sessionQuery,
    configQuery,
    charactersQuery,
    backgroundsQuery,
    effectsQuery,
  ].find((query) => query.isError);
  const failedQuery = failedQueryRaw
    ? { error: failedQueryRaw.error as unknown, refetch: () => failedQueryRaw.refetch() as Promise<unknown> }
    : undefined;
  const templateSelectValue = !isCreating && !sessionDraftActive ? selectedId || selected?.id || "" : "";

  const baseScenario = draft.baseScenario ?? draft.scenario ?? "";
  const resolvedSelectedPresets = useMemo(
    () =>
      resolveSelectedPresets(draft.selectedPresetIds ?? [], presetsLibrary, draft.appliedPresets ?? [], {
        libraryLoaded: presetsLibraryReady,
      }),
    [draft.appliedPresets, draft.selectedPresetIds, presetsLibrary, presetsLibraryReady],
  );
  const composedScenario = useMemo(
    () => composeScenarioWithPresets(baseScenario, resolvedSelectedPresets),
    [baseScenario, resolvedSelectedPresets],
  );
  const appliedPresetsSnapshot = useMemo(() => toAppliedPresets(resolvedSelectedPresets), [resolvedSelectedPresets]);
  const effectiveSelectedPresetIds =
    presetsLibraryReady || (draft.appliedPresets?.length ?? 0) > 0
      ? resolvedSelectedPresets.map((item) => item.id)
      : (draft.selectedPresetIds ?? []);

  const selectedCharactersKey = selectedCharacters.join("\n");
  const generationCharactersKey = templateGenerationKey({
    characters: selectedCharacters,
    characterPromptMode,
    primaryCharacters,
    mediaSelectionMode,
    ...playerOptions,
  });
  const fullSystemSyncKey = buildSystemSyncKey({
    characterKey: generationCharactersKey,
    backgroundName: selectedBackground,
    voiceLanguage,
    useCg,
    useEffect: useEffectPrompt,
    useTranslation,
    useCot,
    useChoice,
    useNarration,
    useStat,
    maxSpeechChars,
    maxDialogItems,
    outputFormat,
  });

  useTemplateRestoreEffects({
    appConfig,
    backgroundOptions,
    characterPromptMode,
    characters,
    conversationId,
    createOnly,
    dialogFormats,
    dialogFormatsLoaded,
    fullSystemSyncKey,
    generationCharactersKey,
    lastAutoGeneratedKeyRef,
    launchSession,
    maxDialogItems,
    maxSpeechChars,
    outputFormat,
    primaryCharacters,
    restoredSessionBackgroundRef,
    selected,
    selectedBackground,
    selectedCharacters,
    sessionDraftActive,
    sessionFetched,
    sessionRestored,
    setAllowPlayerDialogue,
    setAutoOutfitSwitch,
    setCharacterPromptMode,
    setDraft,
    setHistoryPath,
    setInitSpritePath,
    setInitialOutfits,
    setManualBaseKey,
    setMaxDialogItems,
    setMaxSpeechChars,
    setMediaSelectionMode,
    setMemoryMode,
    setNameError,
    setOutputFormat,
    setPlayerCharacter,
    setPrimaryCharacters,
    setReadPlayerSpeech,
    setRoomId,
    setSelectedBackground,
    setSelectedCharacters,
    setSelectedEffects,
    setSelectedId,
    setSessionDraftActive,
    setSessionRestored,
    setShowInitialSprite,
    setSystemManuallyEdited,
    setUseCg,
    setUseChoice,
    setUseCot,
    setUseEffectPrompt,
    setUseNarration,
    setUseStat,
    setUseTranslation,
    setVoiceLanguage,
    suppressNextAutoGenerateRef,
    templates,
    templatesPending: templatesQuery.isPending,
    useCg,
    useChoice,
    useCot,
    useEffectPrompt,
    useNarration,
    useStat,
    useTranslation,
    voiceLanguage,
  });

  const updateDraft = (patch: Partial<TemplateSummary>) => {
    if (patch.system !== undefined) {
      restoredSessionBackgroundRef.current = null;
    }
    setDraft((current) => {
      const next = { ...current, ...patch };
      const nextBase = String(next.baseScenario ?? next.scenario ?? "");
      const nextIds = next.selectedPresetIds ?? [];
      const nextApplied = next.appliedPresets ?? [];
      const resolved = resolveSelectedPresets(nextIds, presetsLibrary, nextApplied, {
        libraryLoaded: presetsLibraryReady,
      });
      const nextScenario =
        patch.scenario !== undefined && patch.baseScenario === undefined
          ? String(patch.scenario)
          : composeScenarioWithPresets(nextBase, resolved);
      const system = String(next.system ?? "");
      return {
        ...next,
        baseScenario: nextBase,
        scenario: nextScenario,
        content: composeTemplateContent(nextScenario, system),
      };
    });
  };

  const scenarioForSelectedCharacters = (nextCharacters = selectedCharacters, currentBase = baseScenario) => {
    const defaultScenario = buildDefaultTemplateScenario(nextCharacters, t("template.defaultScenario"));
    if (!defaultScenario) {
      if (currentBase === lastAutoScenarioRef.current) {
        return "";
      }
      return currentBase;
    }
    if (!currentBase.trim() || currentBase === lastAutoScenarioRef.current) {
      return defaultScenario;
    }
    return currentBase;
  };

  const effectiveSummaryDraft = () => ({
    ...draft,
    appliedPresets: appliedPresetsSnapshot,
    baseScenario,
    outputFormat,
    scenario: composedScenario,
    selectedPresetIds: effectiveSelectedPresetIds,
  });

  const templateOptionsState = {
    useCg,
    useChoice,
    useCot,
    useEffect: useEffectPrompt,
    useNarration,
    useStat,
    useTranslation,
  };
  const runtimeOptionsState = {
    historyPath,
    initSpritePath,
    showInitialSprite,
    maxDialogItems,
    maxSpeechChars,
    roomId,
    voiceLanguage,
  };

  return {
    allowPlayerDialogue,
    appliedPresetsSnapshot,
    autoGenerateReadyRef,
    autoOutfitSwitch,
    backgroundOptions,
    baseScenario,
    characterByName,
    characterDialogError,
    characterDialogOpen,
    characterPromptMode,
    characters,
    composedScenario,
    deferredLaunchRef,
    dialogFormats,
    draft,
    effectivePlayerCharacter,
    effectiveSelectedPresetIds,
    effectiveSummaryDraft,
    effects,
    failedQuery,
    fullSystemSyncKey,
    historyPath,
    initialOutfits,
    initSpritePath,
    isCreating,
    isLoading,
    lastAutoGeneratedKeyRef,
    lastAutoScenarioRef,
    launchReadyAfterRoleGeneration,
    manualBaseKey,
    maxDialogItems,
    maxSpeechChars,
    mediaSelectionMode,
    memoryMode,
    mobileAccessEnabled,
    nameError,
    outputFormat,
    playerCharacter,
    playerOptions,
    presetsError: presetsQuery.error as unknown,
    presetsIsError: presetsQuery.isError,
    presetsLibrary,
    presetsLibraryReady,
    presetsPending: presetsQuery.isPending,
    presetsSuccess: presetsQuery.isSuccess,
    refetchPresets: () => presetsQuery.refetch() as Promise<unknown>,
    primaryCharacterDialogOpen,
    primaryCharacters,
    readPlayerSpeech,
    resolvedSelectedPresets,
    restoredSessionBackgroundRef,
    runtimeOptionsState,
    scenarioForSelectedCharacters,
    selected,
    selectedBackground,
    selectedCharacterRecords,
    selectedCharacters,
    selectedCharactersKey,
    selectedEffectNames,
    selectedEffects,
    selectedId,
    sessionDraftActive,
    sessionRestored,
    setAllowPlayerDialogue,
    setAutoOutfitSwitch,
    setCharacterDialogError,
    setCharacterDialogOpen,
    setCharacterPromptMode,
    setDraft,
    setHistoryPath,
    setInitialOutfits,
    setInitSpritePath,
    setIsCreating,
    setLaunchReadyAfterRoleGeneration,
    setManualBaseKey,
    setMaxDialogItems,
    setMaxSpeechChars,
    setMediaSelectionMode,
    setMemoryMode,
    setNameError,
    setOutputFormat,
    setPlayerCharacter,
    setPrimaryCharacterDialogOpen,
    setPrimaryCharacters,
    setReadPlayerSpeech,
    setSelectedBackground,
    setSelectedCharacters,
    setSelectedEffects,
    setSelectedId,
    setSessionDraftActive,
    setShowInitialSprite,
    setSystemManuallyEdited,
    setSystemPromptDialogOpen,
    setUseCg,
    setUseChoice,
    setUseCot,
    setUseEffectPrompt,
    setUseNarration,
    setUseStat,
    setUseTranslation,
    setUserPromptDialogOpen,
    setVoiceLanguage,
    showInitialSprite,
    suppressNextAutoGenerateRef,
    systemManuallyEdited,
    systemPromptDialogOpen,
    templateOptionsState,
    templatePlayerOptions,
    templateSelectValue,
    templates,
    updateDraft,
    useCg,
    useChoice,
    useCot,
    useEffectPrompt,
    useNarration,
    useStat,
    useTranslation,
    userPromptDialogOpen,
    voiceLanguage,
  };
}

export type TemplateSessionState = ReturnType<typeof useTemplateSessionState>;
