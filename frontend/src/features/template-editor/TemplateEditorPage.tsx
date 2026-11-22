import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Play, RotateCcw, RotateCw, Save } from "lucide-react";

import { backgroundsQueryKey, listBackgrounds } from "../../entities/background/repository";
import { charactersQueryKey, ensureCharacterBriefs, listCharacters } from "../../entities/character/repository";
import { resolveConversationTitle } from "../../entities/chat/conversationTitle";
import { effectsQueryKey, listEffects } from "../../entities/effect/repository";
import {
  conversationsQueryKey,
  getConversationSession,
  installMissingRuntimeDependency,
  launchChat,
  reconfigureConversation,
} from "../../entities/chat/repository";
import { ChatInitializationDialog } from "../chat-startup/ChatInitializationDialog";
import { MobileAccessDialog } from "../mobile-access/MobileAccessDialog";
import { useMobileAccessPreference } from "../mobile-access/useMobileAccessPreference";
import { useChatInitialization, type ChatInitializationService } from "../chat-startup/useChatInitialization";
import { compatibleInitialSpritePath } from "../chat-startup/initialSpriteSelection";
import { useChatLaunchGuard } from "../chat-startup/useChatLaunchGuard";
import { configQueryKey, getAppConfig, saveSystemConfig } from "../../entities/config/repository";
import {
  generateTemplate,
  getTemplateSession,
  getUserPromptPresets,
  listTemplates,
  saveTemplate,
  saveTemplateSession,
  saveUserPromptPresets,
  templatesQueryKey,
  userPromptPresetsQueryKey,
  type TemplateSummary,
  type UserPromptPresetLibrary,
} from "../../entities/template/repository";
import { DEFAULT_SPRITE_GROUP, TRANSPARENT_BACKGROUND_NAME } from "../../shared/constants";
import {
  DEFAULT_PLAYER_OPTIONS,
  getCharacterDisplayName,
  normalizePlayerOptions,
} from "../../shared/playerCharacterOptions";
import { showChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import { platformErrorCode } from "../../shared/platform/errors";
import type {
  CharacterPromptMode,
  ChatSnapshot,
  InitialOutfitValue,
  MediaSelectionMode,
  MemoryMode,
  MobileAccessInfo,
  TemplateLaunchSession,
} from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  QueryErrorState,
  Select,
  Switch,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";
import {
  buildChatLaunchPayload,
  buildDefaultTemplateScenario,
  buildTemplateGenerateInput,
  buildTemplateLaunchSession,
  buildTemplateSummary,
  composeTemplateContent,
  createTemplateDraft,
  normalizeTemplateSummary,
  synchronizeChatLaunchPayloadWithSession,
  synchronizeTemplateLaunchSessionWithSnapshot,
  templateGenerationKey,
  templateVoiceLanguages,
} from "./templateFlow";
import { CharacterConfigDialog, type CharacterConfigCommit } from "./CharacterConfigDialog";
import { PrimaryCharacterDialog } from "./PrimaryCharacterDialog";
import { useSemanticMediaController } from "./SemanticMediaSwitch";
import { SystemPromptDialog, type SystemPromptCommit, type SystemPromptRulesDraft } from "./SystemPromptDialog";
import { UserPromptPresetsDialog, type UserPromptCommit } from "./UserPromptPresetsDialog";
import {
  composeScenarioWithPresets,
  normalizeUserPromptPresetLibrary,
  resolveSelectedPresets,
  toAppliedPresets,
} from "./userPromptPresets";
import "./TemplateEditorPage.css";

const voiceLanguages = templateVoiceLanguages;
const MAX_VISIBLE_PRESET_CHIPS = 6;

function characterOutfitGroups(character: {
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

function buildSystemSyncKey(input: {
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
  ].join("\n::");
}

export function TemplateEditorPage({
  createOnly = false,
  conversationId,
  conversationTitle,
  onApplied,
  onPendingChange,
  initializationService,
  onLaunchStarted,
}: {
  createOnly?: boolean;
  conversationId?: string;
  conversationTitle?: string;
  onApplied?: (snapshot: ChatSnapshot) => void;
  onPendingChange?: (pending: boolean) => void;
  initializationService?: ChatInitializationService;
  onLaunchStarted?: () => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
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
  const { refreshRuntimeStatus, runtimeLaunchDisabled, runtimeClosing, updateRuntimeStatusFromSnapshot } =
    useChatLaunchGuard();
  const localInitialization = useChatInitialization();
  const {
    closeInitialization,
    initializationError,
    initializationOpen,
    initializationPending,
    initializationTask,
    runChatInitialization,
  } = initializationService ?? localInitialization;
  useEffect(() => onPendingChange?.(initializationPending), [initializationPending, onPendingChange]);

  const templates = templatesQuery.data ?? [];
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
  const [mobileAccessInfo, setMobileAccessInfo] = useState<MobileAccessInfo | null>(null);
  const [maxSpeechChars, setMaxSpeechChars] = useState(0);
  const [maxDialogItems, setMaxDialogItems] = useState(0);
  const [initSpritePath, setInitSpritePath] = useState("");
  const [showInitialSprite, setShowInitialSprite] = useState(true);
  const [memoryMode, setMemoryMode] = useState<MemoryMode>("isolated");
  const [autoOutfitSwitch, setAutoOutfitSwitch] = useState(true);
  const [initialOutfits, setInitialOutfits] = useState<Record<string, string>>({});
  const [historyPath, setHistoryPath] = useState("");
  const [roomId, setRoomId] = useState("");
  const [quickRestartOpen, setQuickRestartOpen] = useState(false);
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
  const failedQuery = [
    templatesQuery,
    presetsQuery,
    sessionQuery,
    configQuery,
    charactersQuery,
    backgroundsQuery,
    effectsQuery,
  ].find((query) => query.isError);
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
  });

  useEffect(() => {
    if (selected && !sessionDraftActive) {
      setSelectedId(selected.id);
      const normalized = normalizeTemplateSummary(structuredClone(selected));
      const nextMediaMode = createOnly ? "indexed" : (selected.mediaSelectionMode ?? "indexed");
      const savedPlayer = normalizePlayerOptions(selected);
      const charKey = templateGenerationKey({
        characters: selectedCharacters,
        characterPromptMode,
        primaryCharacters,
        mediaSelectionMode: nextMediaMode,
        playerCharacter: selectedCharacters.includes(savedPlayer.playerCharacter) ? savedPlayer.playerCharacter : "",
        readPlayerSpeech: savedPlayer.readPlayerSpeech,
        allowPlayerDialogue: savedPlayer.allowPlayerDialogue,
      });
      lastAutoGeneratedKeyRef.current = buildSystemSyncKey({
        characterKey: charKey,
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
      });
      setDraft(normalized);
      setMediaSelectionMode(nextMediaMode);
      setPlayerCharacter(savedPlayer.playerCharacter);
      setReadPlayerSpeech(Boolean(savedPlayer.playerCharacter && savedPlayer.readPlayerSpeech));
      setAllowPlayerDialogue(savedPlayer.allowPlayerDialogue);
      setSystemManuallyEdited(false);
      setManualBaseKey("");
      setNameError("");
    }
  }, [createOnly, selected, sessionDraftActive]);

  useEffect(() => {
    if (!sessionFetched || sessionRestored) {
      return;
    }
    if (!conversationId && launchSession?.templateFileDropdown && templatesQuery.isPending) {
      return;
    }
    if (!launchSession) {
      setSessionRestored(true);
      return;
    }
    const restoredCharacters = Array.isArray(launchSession.selectedCharacters) ? launchSession.selectedCharacters : [];
    const restoredMode = launchSession.characterPromptMode ?? (restoredCharacters.length <= 4 ? "full" : undefined);
    const restoredPrimaryCharacters =
      restoredMode === "full"
        ? restoredCharacters
        : Array.isArray(launchSession.primaryCharacters)
          ? launchSession.primaryCharacters.filter((name) => restoredCharacters.includes(name))
          : [];
    const restoredMediaSelectionMode = createOnly ? "indexed" : (launchSession.mediaSelectionMode ?? "indexed");
    const restoredPlayer = normalizePlayerOptions(launchSession);
    const sessionBackground = launchSession.background || TRANSPARENT_BACKGROUND_NAME;
    const restoredBackground = createOnly ? TRANSPARENT_BACKGROUND_NAME : sessionBackground;
    restoredSessionBackgroundRef.current = sessionBackground !== restoredBackground ? sessionBackground : null;

    const restoredEffects = Array.isArray(launchSession.effectNames) ? launchSession.effectNames : [];
    const restoredVoiceLanguage = launchSession.voiceLanguage || "ja";
    const restoredUseEffect = launchSession.useEffect ?? true;
    const restoredUseTranslation = launchSession.useTranslation ?? true;
    const restoredUseCg = launchSession.useCg ?? false;
    const restoredUseCot = launchSession.useCot ?? false;
    const restoredUseChoice = launchSession.useChoice ?? true;
    const restoredUseNarration = launchSession.useNarration ?? true;
    const restoredUseStat = launchSession.useStat ?? true;
    const restoredMaxSpeech = Number(launchSession.maxSpeechChars) || 0;
    const restoredMaxDialog = Number(launchSession.maxDialogItems) || 0;

    const restoredCharKey = templateGenerationKey({
      characters: restoredCharacters,
      characterPromptMode: restoredMode,
      primaryCharacters: restoredPrimaryCharacters,
      mediaSelectionMode: restoredMediaSelectionMode,
      ...restoredPlayer,
    });
    const restoredSyncKey = buildSystemSyncKey({
      characterKey: restoredCharKey,
      backgroundName: restoredBackground,
      voiceLanguage: restoredVoiceLanguage,
      useCg: restoredUseCg,
      useEffect: restoredUseEffect,
      useTranslation: restoredUseTranslation,
      useCot: restoredUseCot,
      useChoice: restoredUseChoice,
      useNarration: restoredUseNarration,
      useStat: restoredUseStat,
      maxSpeechChars: restoredMaxSpeech,
      maxDialogItems: restoredMaxDialog,
    });
    lastAutoGeneratedKeyRef.current = restoredSyncKey;

    const restoredManuallyEdited = Boolean(launchSession.systemManuallyEdited);
    setSystemManuallyEdited(restoredManuallyEdited);
    setManualBaseKey(restoredManuallyEdited ? restoredSyncKey : "");

    setSessionDraftActive(true);
    setSelectedCharacters(restoredCharacters);
    setPlayerCharacter(restoredPlayer.playerCharacter);
    setReadPlayerSpeech(restoredPlayer.readPlayerSpeech);
    setAllowPlayerDialogue(restoredPlayer.allowPlayerDialogue);
    setCharacterPromptMode(restoredMode);
    setPrimaryCharacters(restoredPrimaryCharacters);
    setMediaSelectionMode(restoredMediaSelectionMode);
    setSelectedBackground(restoredBackground);
    setSelectedEffects(restoredEffects);
    setVoiceLanguage(restoredVoiceLanguage);
    setUseEffectPrompt(restoredUseEffect);
    setUseTranslation(restoredUseTranslation);
    setUseCg(restoredUseCg);
    setUseCot(restoredUseCot);
    setUseChoice(restoredUseChoice);
    setUseNarration(restoredUseNarration);
    setUseStat(restoredUseStat);
    setMaxSpeechChars(restoredMaxSpeech);
    setMaxDialogItems(restoredMaxDialog);
    setInitSpritePath(launchSession.initSpritePath || "");
    setShowInitialSprite(launchSession.showInitialSprite ?? true);
    setMemoryMode(launchSession.memoryMode ?? "isolated");
    setAutoOutfitSwitch(launchSession.autoOutfitSwitch ?? true);
    if (launchSession.initialOutfits && typeof launchSession.initialOutfits === "object") {
      const restoredOutfits: Record<string, string> = {};
      for (const [charName, rawOutfit] of Object.entries(launchSession.initialOutfits)) {
        const group = typeof rawOutfit === "string" ? rawOutfit.trim() : String(rawOutfit?.activeGroup ?? "").trim();
        if (charName && group) {
          restoredOutfits[charName] = group;
        }
      }
      setInitialOutfits(restoredOutfits);
    }
    setHistoryPath(launchSession.historyPath || "");
    setRoomId(launchSession.roomId || "");
    const matchingTemplate = templates.find((template) => template.id === launchSession.templateFileDropdown);
    setSelectedId(matchingTemplate?.id ?? "");
    const restoredSelectedPresetIds = Array.isArray(launchSession.selectedPresetIds)
      ? launchSession.selectedPresetIds
      : [];
    const restoredAppliedPresets = Array.isArray(launchSession.appliedPresets) ? launchSession.appliedPresets : [];
    const restoredBaseScenario =
      launchSession.baseScenario !== undefined ? launchSession.baseScenario : launchSession.scenario;
    setDraft(
      normalizeTemplateSummary({
        appliedPresets: restoredAppliedPresets,
        baseScenario: restoredBaseScenario,
        content: composeTemplateContent(launchSession.scenario, launchSession.system),
        id: matchingTemplate?.id ?? "",
        name: launchSession.filenameStub || matchingTemplate?.name || t("template.defaultName"),
        path: matchingTemplate?.path ?? "",
        mediaSelectionMode: launchSession.mediaSelectionMode ?? "indexed",
        ...restoredPlayer,
        scenario: launchSession.scenario,
        selectedPresetIds: restoredSelectedPresetIds,
        system: launchSession.system,
        updatedAt: matchingTemplate?.updatedAt ?? "",
      }),
    );
    setSessionRestored(true);
  }, [
    conversationId,
    createOnly,
    launchSession,
    sessionFetched,
    sessionRestored,
    t,
    templates,
    templatesQuery.isPending,
  ]);

  useEffect(() => {
    if (!backgroundOptions.includes(selectedBackground)) {
      setSelectedBackground(TRANSPARENT_BACKGROUND_NAME);
    }
  }, [backgroundOptions, selectedBackground]);

  useEffect(() => {
    if (!sessionRestored || launchSession) {
      return;
    }
    const configuredLanguage = String(appConfig?.system_config.voice_language || "")
      .trim()
      .toLowerCase();
    const nextLanguage = voiceLanguages.some((option) => option.value === configuredLanguage)
      ? configuredLanguage
      : "ja";
    if (!configuredLanguage || nextLanguage === voiceLanguage) {
      return;
    }
    suppressNextAutoGenerateRef.current = true;
    setVoiceLanguage(nextLanguage);
  }, [appConfig, launchSession, sessionRestored, voiceLanguage]);

  useEffect(() => {
    if (!sessionRestored) {
      return;
    }
    setInitSpritePath((current) => compatibleInitialSpritePath({ characters, path: current, selectedCharacters }));
  }, [characters, selectedCharacters, sessionRestored]);

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

  const validateName = () => {
    if (!draft.name.trim()) {
      setNameError(t("template.validation.nameRequired"));
      return false;
    }
    setNameError("");
    return true;
  };

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

  const handleRuntimeDependencyError = async (snapshot: ChatSnapshot) => {
    const dependencyError = snapshot.runtimeDependencyError;
    if (!dependencyError) {
      return false;
    }
    const shouldInstall = window.confirm(
      t("runtimeDeps.installConfirm", {
        module: dependencyError.moduleName,
        package: dependencyError.packageName,
      }),
    );
    if (!shouldInstall) {
      showToast({ kind: "error", message: snapshot.dialogText, title: t("template.error.launchFailed") });
      return true;
    }
    try {
      const result = await installMissingRuntimeDependency({ moduleName: dependencyError.moduleName });
      showToast({
        kind: "success",
        message: result.message || t("runtimeDeps.installSucceeded"),
        title: t("runtimeDeps.installTitle"),
      });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("runtimeDeps.installFailed"),
        title: t("runtimeDeps.installFailed"),
      });
    }
    return true;
  };

  const effectiveSummaryDraft = () => ({
    ...draft,
    appliedPresets: appliedPresetsSnapshot,
    baseScenario,
    scenario: composedScenario,
    selectedPresetIds: effectiveSelectedPresetIds,
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!validateName()) {
        throw new Error(t("template.validation.nameRequired"));
      }
      return saveTemplate({
        ...buildTemplateSummary(effectiveSummaryDraft()),
        ...templatePlayerOptions,
      });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("template.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(template) {
      queryClient.invalidateQueries({ queryKey: templatesQueryKey });
      const normalized = normalizeTemplateSummary(template);
      setIsCreating(false);
      setSessionDraftActive(false);
      setDraft(normalized);
      setSelectedId(normalized.id);
      showToast({ kind: "success", title: t("template.toast.saved") });
    },
  });

  const savePresetsMutation = useMutation({
    mutationFn: async (library: UserPromptPresetLibrary) => {
      if (!presetsQuery.isSuccess) {
        throw new Error(
          presetsQuery.error instanceof Error ? presetsQuery.error.message : t("template.presets.loadFailed"),
        );
      }
      return saveUserPromptPresets(library);
    },
    onSuccess(saved) {
      queryClient.setQueryData(userPromptPresetsQueryKey, saved);
    },
  });

  const voiceLanguageMutation = useMutation({
    mutationFn: async (language: string) => {
      const config = await getAppConfig();
      return saveSystemConfig({
        ...config.system_config,
        voice_language: language,
      });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("system.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
  });

  const ensureBriefsMutation = useMutation({
    mutationFn: ensureCharacterBriefs,
  });

  const generationInput = (
    nextBaseScenario = scenarioForSelectedCharacters(),
    overrides?: Partial<SystemPromptRulesDraft>,
  ) => {
    const nextScenario = composeScenarioWithPresets(nextBaseScenario, resolvedSelectedPresets);
    const effectiveMode = overrides?.mediaSelectionMode ?? mediaSelectionMode;
    const effectiveOptions = {
      useCg,
      useChoice: overrides?.useChoice ?? useChoice,
      useCot: overrides?.useCot ?? useCot,
      useEffect: overrides?.useEffectPrompt ?? useEffectPrompt,
      useNarration: overrides?.useNarration ?? useNarration,
      useStat: overrides?.useStat ?? useStat,
      useTranslation: overrides?.useTranslation ?? useTranslation,
    };
    const effectiveRuntime = {
      ...runtimeOptionsState,
      maxDialogItems: overrides?.maxDialogItems ?? maxDialogItems,
      maxSpeechChars: overrides?.maxSpeechChars ?? maxSpeechChars,
    };
    return buildTemplateGenerateInput({
      backgroundName: selectedBackground,
      characterPromptMode: characterPromptMode ?? "full",
      draft: { ...draft, scenario: nextScenario },
      effectNames: selectedEffects,
      mediaSelectionMode: effectiveMode,
      options: effectiveOptions,
      runtime: effectiveRuntime,
      primaryCharacters: characterPromptMode === "compact" ? primaryCharacters : selectedCharacters,
      ...playerOptions,
      selectedCharacters,
    });
  };
  const latestGenerationInput = useRef(generationInput);
  useLayoutEffect(() => {
    latestGenerationInput.current = generationInput;
  });

  const applyResolvedCharactersFromGeneration = (resolvedCharacters: string[]) => {
    const resolvedCharactersKey = resolvedCharacters.join("\n");
    if (resolvedCharactersKey === selectedCharactersKey) {
      return;
    }
    suppressNextAutoGenerateRef.current = true;
    const resolvedPrimary = primaryCharacters.filter((name) => resolvedCharacters.includes(name));
    const nextCharKey = templateGenerationKey({
      characters: resolvedCharacters,
      characterPromptMode: characterPromptMode ?? "full",
      primaryCharacters: resolvedPrimary,
      mediaSelectionMode,
      ...playerOptions,
      playerCharacter: resolvedCharacters.includes(playerCharacter) ? playerCharacter : "",
    });
    lastAutoGeneratedKeyRef.current = buildSystemSyncKey({
      characterKey: nextCharKey,
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
    });
    setPrimaryCharacters(resolvedPrimary);
    setSelectedCharacters(resolvedCharacters);
    setInitSpritePath((path) =>
      compatibleInitialSpritePath({
        characters,
        path,
        preserveUnknown: false,
        selectedCharacters: resolvedCharacters,
      }),
    );
  };

  const generateMutation = useMutation({
    // Mutation callbacks are refreshed in a passive effect. Pass the visible
    // form as variables so a click immediately after restoration cannot use
    // the previous render's draft.
    mutationFn: ({
      input,
    }: {
      input: ReturnType<typeof buildTemplateGenerateInput>;
      silent?: boolean;
      previewOnly?: boolean;
      meta?: {
        baseScenario: string;
        selectedPresetIds: string[];
        appliedPresets: ReturnType<typeof toAppliedPresets>;
      };
    }) => generateTemplate(input),
    onError(error, options) {
      const wasPreparingLaunch = deferredLaunchRef.current !== null;
      deferredLaunchRef.current = null;
      if (options?.silent && !wasPreparingLaunch) {
        return;
      }
      showToast({
        kind: "error",
        message:
          platformErrorCode(error) === "no_valid_characters"
            ? t("template.validation.charactersRequired")
            : error instanceof Error
              ? error.message
              : t("template.error.generateFallback"),
        title: t("template.error.generateFailed"),
      });
    },
    onSuccess(template, options) {
      if (Array.isArray(template.resolvedCharacters)) {
        applyResolvedCharactersFromGeneration(template.resolvedCharacters);
      }
      if (options?.previewOnly) {
        if (!options?.silent) {
          showToast({ kind: "success", message: template.generationMessage, title: t("template.toast.generated") });
        }
        return;
      }
      const normalized = normalizeTemplateSummary({
        ...template,
        appliedPresets: options.meta?.appliedPresets ?? [],
        baseScenario: options.meta?.baseScenario ?? template.scenario ?? options.input.scenario ?? "",
        scenario: template.scenario || options.input.scenario || "",
        selectedPresetIds: options.meta?.selectedPresetIds ?? [],
      });
      restoredSessionBackgroundRef.current = null;
      setIsCreating(true);
      setSessionDraftActive(true);
      setDraft(normalized);
      if (!options?.silent) {
        showToast({ kind: "success", message: template.generationMessage, title: t("template.toast.generated") });
      }
      if (deferredLaunchRef.current !== null) {
        setLaunchReadyAfterRoleGeneration(deferredLaunchRef.current);
        deferredLaunchRef.current = null;
      }
    },
  });

  useEffect(() => {
    if (!sessionRestored) {
      return;
    }
    if (!autoGenerateReadyRef.current) {
      autoGenerateReadyRef.current = true;
      return;
    }
    if (suppressNextAutoGenerateRef.current) {
      suppressNextAutoGenerateRef.current = false;
      return;
    }
    if (generateMutation.isPending) {
      return;
    }
    if (selectedCharacters.length === 0) {
      return;
    }
    if (selectedCharacters.length > 4 && !characterPromptMode) {
      return;
    }
    if (fullSystemSyncKey === lastAutoGeneratedKeyRef.current) {
      return;
    }
    const nextBase = scenarioForSelectedCharacters();
    if (nextBase !== baseScenario) {
      lastAutoScenarioRef.current = nextBase;
      updateDraft({ baseScenario: nextBase });
    }
    if (systemManuallyEdited) {
      return;
    }
    const scheduledKey = fullSystemSyncKey;
    const presetMeta = {
      appliedPresets: appliedPresetsSnapshot,
      baseScenario: nextBase,
      selectedPresetIds: effectiveSelectedPresetIds,
    };
    const timer = window.setTimeout(() => {
      lastAutoGeneratedKeyRef.current = scheduledKey;
      generateMutation.mutate({
        input: latestGenerationInput.current(nextBase),
        meta: presetMeta,
        silent: true,
      });
    }, 160);
    return () => window.clearTimeout(timer);
  }, [fullSystemSyncKey, sessionRestored, systemManuallyEdited, selectedCharacters.length, characterPromptMode]);

  const launchMutation = useMutation({
    mutationFn: async ({
      resetHistory,
      template,
      session,
    }: {
      resetHistory: boolean;
      template: TemplateSummary;
      session: TemplateLaunchSession;
    }) => {
      if (runtimeClosing || (runtimeLaunchDisabled && !conversationId)) {
        throw new Error(t("launch.runtimeBusy"));
      }
      return runChatInitialization(async (progressOptions) => {
        onLaunchStarted?.();
        const savedSession = conversationId ? session : await saveTemplateSession(session);
        if (!conversationId) queryClient.setQueryData([...templatesQueryKey, "session"], savedSession);
        const apply = conversationId
          ? (payload: Parameters<typeof launchChat>[0], options: Parameters<typeof launchChat>[1]) =>
              reconfigureConversation(conversationId, payload, options)
          : launchChat;
        const snapshot = await apply(
          {
            ...synchronizeChatLaunchPayloadWithSession(
              buildChatLaunchPayload({
                backgroundName: session.background,
                effectNames: session.effectNames,
                mobileAccessEnabled: Boolean(session.enableMobileAccess),
                mediaSelectionMode: session.mediaSelectionMode ?? "indexed",
                resetHistory: conversationId ? false : createOnly || resetHistory,
                runtime: session,
                selectedCharacters: session.selectedCharacters,
                template,
                useCg: session.useCg,
              }),
              savedSession,
            ),
            editorSession: savedSession,
            ...(createOnly ? { conversationTitle: resolveConversationTitle(conversationTitle) } : {}),
          },
          progressOptions,
        );
        const confirmedSession = synchronizeTemplateLaunchSessionWithSnapshot(savedSession, snapshot);
        if (confirmedSession !== savedSession) {
          queryClient.setQueryData(
            conversationId ? [...conversationsQueryKey, conversationId, "settings"] : [...templatesQueryKey, "session"],
            confirmedSession,
          );
          setHistoryPath(confirmedSession.historyPath);
        }
        return { snapshot, template };
      });
    },
    onError(error) {
      void refreshRuntimeStatus();
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("template.error.launchFailed"),
        title: t("template.error.launchFailed"),
      });
    },
    onSuccess({ snapshot, template }) {
      void queryClient.invalidateQueries({ queryKey: conversationsQueryKey });
      void updateRuntimeStatusFromSnapshot(snapshot);
      const normalized = normalizeTemplateSummary(template);
      setSessionDraftActive(true);
      setDraft(normalized);
      if (snapshot.runtimeDependencyError) {
        void handleRuntimeDependencyError(snapshot);
        return;
      }
      if (onApplied) {
        onApplied(snapshot);
        return;
      }
      showToast({
        kind: "success",
        message: snapshot.statusMessage || snapshot.dialogText,
        title: t("template.toast.launched"),
      });
      if (snapshot.mobileAccess) {
        setMobileAccessInfo(snapshot.mobileAccess);
        return;
      }
      void showChatSurface({ snapshot });
    },
  });

  const launchCurrentDraft = (resetHistory: boolean) => {
    const summaryDraft = effectiveSummaryDraft();
    const template = {
      ...buildTemplateSummary(summaryDraft),
      ...templatePlayerOptions,
    };
    const filteredInitialOutfits: Record<string, InitialOutfitValue> = {};
    for (const character of selectedCharacterRecords) {
      const chosen = initialOutfits[character.name]?.trim();
      if (chosen && characterOutfitGroups(character).includes(chosen)) {
        filteredInitialOutfits[character.name] = chosen;
      }
    }
    const session: TemplateLaunchSession = buildTemplateLaunchSession({
      appliedPresets: appliedPresetsSnapshot,
      autoOutfitSwitch,
      backgroundName: selectedBackground,
      baseScenario,
      characterPromptMode: characterPromptMode ?? "full",
      draft: summaryDraft,
      effectNames: selectedEffects,
      initialOutfits: filteredInitialOutfits,
      memoryMode,
      mobileAccessEnabled,
      mediaSelectionMode,
      options: templateOptionsState,
      primaryCharacters: characterPromptMode === "compact" ? primaryCharacters : selectedCharacters,
      ...playerOptions,
      runtime: createOnly ? { ...runtimeOptionsState, historyPath: "" } : runtimeOptionsState,
      selectedCharacters,
      selectedPresetIds: effectiveSelectedPresetIds,
      selectedTemplateId: selectedId,
      systemManuallyEdited,
    });
    launchMutation.mutate({ resetHistory, template, session });
  };

  useEffect(() => {
    if (launchReadyAfterRoleGeneration === null) {
      return;
    }
    const resetHistory = launchReadyAfterRoleGeneration;
    setLaunchReadyAfterRoleGeneration(null);
    launchCurrentDraft(resetHistory);
  }, [launchReadyAfterRoleGeneration]);

  const confirmCharacterConfig = async (next: CharacterConfigCommit) => {
    setCharacterDialogError("");
    const effectivePlayer = next.selectedCharacters.includes(next.playerCharacter) ? next.playerCharacter : "";
    let resolvedMode = next.characterPromptMode;
    let resolvedPrimary = next.primaryCharacters;

    if (resolvedMode === "compact") {
      const secondary = next.selectedCharacters.filter(
        (name) => name !== effectivePlayer && !resolvedPrimary.includes(name),
      );
      try {
        const result = await ensureBriefsMutation.mutateAsync(secondary);
        if (result.characters.length) {
          const updated = new Map(result.characters.map((character) => [character.name, character]));
          queryClient.setQueryData(charactersQueryKey, (current: typeof characters = []) =>
            current.map((character) => updated.get(character.name) ?? character),
          );
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : t("character.error.aiFallback");
        setCharacterDialogError(message);
        showToast({
          kind: "error",
          message,
          title: t("template.primaryCharacters.title"),
        });
        return;
      }
    } else if (resolvedMode === "full") {
      resolvedPrimary = next.selectedCharacters;
    }

    setSelectedCharacters(next.selectedCharacters);
    setCharacterPromptMode(resolvedMode);
    setPrimaryCharacters(resolvedPrimary);
    setPlayerCharacter(effectivePlayer);
    setReadPlayerSpeech(Boolean(effectivePlayer && next.readPlayerSpeech));
    setAllowPlayerDialogue(next.allowPlayerDialogue);
    setInitSpritePath((path) =>
      compatibleInitialSpritePath({
        characters,
        path,
        preserveUnknown: false,
        selectedCharacters: next.selectedCharacters,
      }),
    );
    setCharacterDialogOpen(false);
  };

  const useAllCharactersAsPrimary = () => {
    setPrimaryCharacters(selectedCharacters);
    setCharacterPromptMode("full");
    setPrimaryCharacterDialogOpen(false);
  };

  const confirmPrimaryCharacters = async (nextPrimaryCharacters: string[]) => {
    const primary = nextPrimaryCharacters.filter((name) => selectedCharacters.includes(name));
    const secondary = selectedCharacters.filter((name) => name !== effectivePlayerCharacter && !primary.includes(name));
    try {
      const result = await ensureBriefsMutation.mutateAsync(secondary);
      if (result.characters.length) {
        const updated = new Map(result.characters.map((character) => [character.name, character]));
        queryClient.setQueryData(charactersQueryKey, (current: typeof characters = []) =>
          current.map((character) => updated.get(character.name) ?? character),
        );
      }
      setPrimaryCharacters(primary);
      setCharacterPromptMode("compact");
      setPrimaryCharacterDialogOpen(false);
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.aiFallback"),
        title: t("template.primaryCharacters.title"),
      });
    }
  };

  const toggleEffect = (name: string, checked: boolean) => {
    setSelectedEffects((current) =>
      checked ? [...new Set([...current, name])] : current.filter((item) => item !== name),
    );
  };

  const handleTemplateSelect = (nextId: string) => {
    if (!nextId) {
      return;
    }
    restoredSessionBackgroundRef.current = null;
    setSessionDraftActive(false);
    setIsCreating(false);
    setSelectedId(nextId);
  };

  const handleVoiceLanguageChange = (nextLanguage: string) => {
    if (nextLanguage === voiceLanguage) {
      return;
    }
    setVoiceLanguage(nextLanguage);
    voiceLanguageMutation.mutate(nextLanguage);
  };

  const handleRegenerateFromDialog = useCallback(
    async (rules: SystemPromptRulesDraft, options: { silent: boolean }): Promise<string | null> => {
      if (!selectedBackground) {
        if (!options.silent) {
          showToast({
            kind: "error",
            message: t("template.validation.backgroundRequired"),
            title: t("template.mode.generate"),
          });
        }
        return null;
      }
      if (!selectedCharacters.length) {
        if (!options.silent) {
          showToast({
            kind: "error",
            message: t("template.validation.charactersRequired"),
            title: t("template.mode.generate"),
          });
        }
        return null;
      }
      if (selectedCharacters.length > 4 && !characterPromptMode) {
        if (!options.silent) {
          setPrimaryCharacterDialogOpen(true);
        }
        return null;
      }
      const nextBase = scenarioForSelectedCharacters();
      if (nextBase !== baseScenario) {
        lastAutoScenarioRef.current = nextBase;
        updateDraft({ baseScenario: nextBase });
      }
      try {
        const result = await generateMutation.mutateAsync({
          input: latestGenerationInput.current(nextBase, rules),
          silent: options.silent,
          previewOnly: true,
        });
        return result.system ?? "";
      } catch {
        return null;
      }
    },
    [baseScenario, characterPromptMode, selectedBackground, selectedCharacters.length, showToast, t],
  );

  const handleConfirmUserPrompt = (commit: UserPromptCommit) => {
    setSessionDraftActive(true);
    updateDraft({
      appliedPresets: commit.appliedPresets,
      selectedPresetIds: commit.selectedPresetIds,
    });
    setUserPromptDialogOpen(false);
  };

  const handleConfirmSystemPrompt = (commit: SystemPromptCommit) => {
    const nextCharKey = templateGenerationKey({
      characters: selectedCharacters,
      characterPromptMode,
      primaryCharacters,
      mediaSelectionMode: commit.mediaSelectionMode,
      ...playerOptions,
    });
    const nextSyncKey = buildSystemSyncKey({
      characterKey: nextCharKey,
      backgroundName: selectedBackground,
      voiceLanguage,
      useCg,
      useEffect: commit.useEffectPrompt,
      useTranslation: commit.useTranslation,
      useCot: commit.useCot,
      useChoice: commit.useChoice,
      useNarration: commit.useNarration,
      useStat: commit.useStat,
      maxSpeechChars: commit.maxSpeechChars,
      maxDialogItems: commit.maxDialogItems,
    });

    // Prevent redundant immediate auto-generation after confirming inside dialog.
    lastAutoGeneratedKeyRef.current = nextSyncKey;
    if (commit.system !== (draft.system ?? "")) {
      setSessionDraftActive(true);
    }
    setMediaSelectionMode(commit.mediaSelectionMode);
    setUseEffectPrompt(commit.useEffectPrompt);
    setUseTranslation(commit.useTranslation);
    setUseCot(commit.useCot);
    setUseChoice(commit.useChoice);
    setUseNarration(commit.useNarration);
    setUseStat(commit.useStat);
    setMaxSpeechChars(commit.maxSpeechChars);
    setMaxDialogItems(commit.maxDialogItems);
    setSystemManuallyEdited(commit.systemManuallyEdited);
    setManualBaseKey(commit.systemManuallyEdited ? nextSyncKey : "");
    updateDraft({
      mediaSelectionMode: commit.mediaSelectionMode,
      system: commit.system,
    });
    setSystemPromptDialogOpen(false);
  };

  const handleLaunch = (resetHistory: boolean) => {
    if (selectedCharacters.length > 4 && !characterPromptMode) {
      deferredLaunchRef.current = resetHistory;
      setPrimaryCharacterDialogOpen(true);
      return;
    }
    // A new chat may reuse a semantic or background-bound session draft while
    // defaulting to indexed selection and a transparent background. Regenerate
    // its instructions before starting that chat.
    if (
      !systemManuallyEdited &&
      (draft.mediaSelectionMode !== mediaSelectionMode ||
        (restoredSessionBackgroundRef.current !== null && restoredSessionBackgroundRef.current !== selectedBackground))
    ) {
      restoredSessionBackgroundRef.current = null;
      deferredLaunchRef.current = resetHistory;
      const nextBase = scenarioForSelectedCharacters();
      generateMutation.mutate({
        input: generationInput(nextBase),
        meta: {
          appliedPresets: appliedPresetsSnapshot,
          baseScenario: nextBase,
          selectedPresetIds: effectiveSelectedPresetIds,
        },
        silent: true,
      });
      return;
    }
    launchCurrentDraft(resetHistory);
  };

  const npcCount = selectedCharacters.filter((name) => name !== effectivePlayerCharacter).length;
  const primaryCount =
    characterPromptMode === "full"
      ? npcCount
      : primaryCharacters.filter((name) => name !== effectivePlayerCharacter).length;
  const showRoleSummary = npcCount > 4 || (npcCount > 0 && Boolean(effectivePlayerCharacter));
  const roleSummaryText =
    characterPromptMode === "full"
      ? t("template.primaryCharacters.statusFull", { count: npcCount })
      : characterPromptMode === "compact"
        ? t("template.primaryCharacters.statusCompact", {
            primary: Math.min(primaryCount, npcCount),
            secondary: Math.max(0, npcCount - Math.min(primaryCount, npcCount)),
          })
        : t("template.primaryCharacters.statusPending", { count: npcCount });

  const defaultScenarioText = buildDefaultTemplateScenario(selectedCharacters, t("template.defaultScenario"));
  const scenarioStatusKey = !baseScenario.trim()
    ? "template.bar.scenarioEmpty"
    : defaultScenarioText && baseScenario === defaultScenarioText
      ? "template.bar.scenarioDefault"
      : "template.bar.scenarioCustom";

  const visiblePresetChips = resolvedSelectedPresets.slice(0, MAX_VISIBLE_PRESET_CHIPS);
  const hiddenPresetCount = Math.max(0, resolvedSelectedPresets.length - visiblePresetChips.length);

  const systemConfigStale = systemManuallyEdited && fullSystemSyncKey !== manualBaseKey;
  const enabledRulesCount = [useEffectPrompt, useTranslation, useCot, useChoice, useNarration, useStat].filter(
    Boolean,
  ).length;
  const systemStatusPill = systemManuallyEdited
    ? {
        className: systemConfigStale ? "is-warning" : "is-manual",
        label: t(systemConfigStale ? "template.bar.systemManualStale" : "template.bar.systemManual"),
      }
    : selectedCharacters.length === 0 && !String(draft.system ?? "").trim()
      ? { className: "is-pending", label: t("template.bar.systemPendingCharacters") }
      : { className: "is-auto", label: t("template.bar.systemAuto") };

  return (
    <div className="page template-page">
      <header className="template-page__topbar">
        <label className="template-topbar-field template-topbar-field--select">
          <span className="template-topbar-field__label">{t("template.section.load")}</span>
          <Select
            disabled={!templates.length}
            onChange={(event) => handleTemplateSelect(event.target.value)}
            value={templateSelectValue}
          >
            <option value="">
              {sessionDraftActive || isCreating ? draft.name || t("template.defaultName") : t("template.section.load")}
            </option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}
              </option>
            ))}
          </Select>
        </label>
        <label className="template-topbar-field">
          <span className="template-topbar-field__label">{t("template.field.templateName")}</span>
          <span className="input-group">
            <TextInput
              className={nameError ? "input--error" : ""}
              onChange={(event) => {
                updateDraft({ name: event.target.value });
                if (event.target.value.trim()) {
                  setNameError("");
                }
              }}
              value={draft.name}
            />
            {!conversationId && (
              <AsyncButton
                className="template-save-button"
                icon={<Save aria-hidden className="button__icon" />}
                loading={saveMutation.isPending}
                onClick={() => saveMutation.mutate()}
              >
                {t("common.save")}
              </AsyncButton>
            )}
          </span>
          {nameError ? <span className="field-error">{nameError}</span> : null}
        </label>
      </header>

      {isLoading || failedQuery || (!templates.length && !failedQuery) ? (
        <div className="template-page__status">
          {isLoading ? <EmptyState title={t("template.loading")} /> : null}
          {failedQuery ? (
            <QueryErrorState
              error={failedQuery.error}
              onRetry={() => void failedQuery.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {!isLoading && !failedQuery && !templates.length ? (
            <EmptyState title={t("template.emptyTitle")} body={t("template.emptyBody")} />
          ) : null}
        </div>
      ) : null}

      <div className="template-workbench">
        <section className="template-workbench__main">
          {/* Bar 1: Selected Characters */}
          <section className="template-summary-bar" data-section="characters">
            <div className="template-summary-bar__header">
              <div className="template-summary-bar__title-group">
                <span className="template-panel__label">{t("template.field.characters")}</span>
                {showRoleSummary ? <span className="template-summary-pill">{roleSummaryText}</span> : null}
              </div>
              <Button
                aria-label={t("template.bar.editCharacters")}
                icon={<Pencil aria-hidden className="button__icon" />}
                onClick={() => {
                  setCharacterDialogError("");
                  setCharacterDialogOpen(true);
                }}
                variant="ghost"
              >
                {t("template.mode.edit")}
              </Button>
            </div>
            <div className="template-summary-bar__body">
              {selectedCharacters.length === 0 ? (
                <span className="template-summary-bar__empty">{t("template.bar.charactersEmpty")}</span>
              ) : (
                <div className="template-summary-chips" role="list">
                  {selectedCharacters.map((name) => {
                    const character = characterByName.get(name);
                    const isPlayer = name === effectivePlayerCharacter;
                    return (
                      <span
                        className={`template-summary-chip${!character ? " is-unavailable" : ""}`}
                        key={name}
                        role="listitem"
                        style={
                          {
                            "--template-character-color": character?.color || "#5b8def",
                          } as CSSProperties
                        }
                      >
                        <span aria-hidden className="template-character-card__dot" />
                        <span className="template-summary-chip__name">
                          {character
                            ? getCharacterDisplayName(character)
                            : t("template.character.unavailable", { name })}
                        </span>
                        {isPlayer ? (
                          <span className="template-summary-chip__badge">{t("template.bar.playerBadge")}</span>
                        ) : null}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
          </section>

          {/* Bar 2: Preset Prompts */}
          <section className="template-summary-bar" data-section="preset-prompts">
            <div className="template-summary-bar__header">
              <div className="template-summary-bar__title-group">
                <span className="template-panel__label">{t("template.bar.presetPrompts")}</span>
                {resolvedSelectedPresets.length > 0 ? (
                  <span className="template-summary-pill">
                    {t("template.bar.presetsSelectedCount", { count: resolvedSelectedPresets.length })}
                  </span>
                ) : null}
              </div>
              <Button
                aria-label={t("template.bar.editPresetPrompts")}
                icon={<Pencil aria-hidden className="button__icon" />}
                onClick={() => setUserPromptDialogOpen(true)}
                variant="ghost"
              >
                {t("template.mode.edit")}
              </Button>
            </div>
            <div className="template-summary-bar__body">
              {resolvedSelectedPresets.length === 0 ? (
                <span className="template-summary-bar__empty">{t("template.bar.noPresets")}</span>
              ) : (
                <div className="template-summary-chips" role="list">
                  {visiblePresetChips.map((preset) => (
                    <span
                      className={`template-summary-chip${preset.isDeleted ? " is-unavailable" : ""}`}
                      key={preset.id}
                      role="listitem"
                      style={
                        {
                          "--template-character-color": preset.color || "#5b8def",
                        } as CSSProperties
                      }
                    >
                      <span aria-hidden className="template-character-card__dot" />
                      <span className="template-summary-chip__name">{preset.name}</span>
                      {preset.isDeleted ? (
                        <span className="template-summary-chip__badge">{t("template.presets.deletedBadge")}</span>
                      ) : null}
                    </span>
                  ))}
                  {hiddenPresetCount > 0 ? (
                    <span className="template-summary-pill">
                      {t("template.bar.moreItems", { count: hiddenPresetCount })}
                    </span>
                  ) : null}
                </div>
              )}
            </div>
          </section>

          {/* Bar 3: System Prompt & Generation Rules */}
          <section className="template-summary-bar" data-section="system-prompt">
            <div className="template-summary-bar__header">
              <div className="template-summary-bar__title-group">
                <span className="template-panel__label">{t("template.bar.systemPrompt")}</span>
                <span className={`template-status-pill ${systemStatusPill.className}`}>{systemStatusPill.label}</span>
              </div>
              <Button
                aria-label={t("template.bar.editSystemPrompt")}
                icon={<Pencil aria-hidden className="button__icon" />}
                onClick={() => setSystemPromptDialogOpen(true)}
                variant="ghost"
              >
                {t("template.mode.edit")}
              </Button>
            </div>
            <div className="template-summary-bar__body">
              <div className="template-summary-chips">
                <span className="template-summary-pill">
                  {t(mediaSelectionMode === "semantic" ? "template.semanticMedia.label" : "template.bar.mediaIndexed")}
                </span>
                <span className="template-summary-pill">
                  {t("template.bar.rulesEnabledCount", { count: enabledRulesCount })}
                </span>
              </div>
            </div>
          </section>

          {/* User Prompt: Direct Editable Input */}
          <section className="template-user-prompt-card" data-section="user-prompt">
            <div className="template-summary-bar__header">
              <div className="template-summary-bar__title-group">
                <label className="template-panel__label" htmlFor="template-user-prompt">
                  {t("template.bar.userPrompt")}
                </label>
                <span className="template-summary-pill">{t(scenarioStatusKey)}</span>
                {resolvedSelectedPresets.length > 0 ? (
                  <span className="template-summary-pill">
                    {t("template.bar.presetsAppendHint", { count: resolvedSelectedPresets.length })}
                  </span>
                ) : null}
              </div>
              <Button
                icon={<RotateCcw aria-hidden className="button__icon" />}
                onClick={() => {
                  const fallback =
                    buildDefaultTemplateScenario(selectedCharacters, t("template.defaultScenario")) ||
                    t("template.defaultScenario");
                  setSessionDraftActive(true);
                  updateDraft({ baseScenario: fallback });
                }}
                variant="ghost"
              >
                {t("template.presets.restoreDefaultScenario")}
              </Button>
            </div>
            <TextArea
              className="template-scenario-textarea"
              id="template-user-prompt"
              onChange={(event) => {
                setSessionDraftActive(true);
                updateDraft({ baseScenario: event.target.value });
              }}
              placeholder={t("template.presets.basePromptPlaceholder")}
              rows={6}
              value={baseScenario}
            />
          </section>
        </section>

        {/* Right Sidebar: Prompt-unrelated Stage & Runtime Settings */}
        <aside className="template-options-panel">
          <div className="template-options-panel__header">
            <h2 className="template-options-panel__title">{t("template.section.stageRuntime")}</h2>
          </div>

          <label className="template-side-field">
            <span className="template-side-field__label">{t("template.field.background")}</span>
            <Select onChange={(event) => setSelectedBackground(event.target.value)} value={selectedBackground}>
              {backgroundOptions.map((name) => (
                <option key={name} value={name}>
                  {name === TRANSPARENT_BACKGROUND_NAME ? t("template.transparentBackground") : name}
                </option>
              ))}
            </Select>
          </label>

          {effects.length > 0 ? (
            <div className="template-side-field template-effect-section">
              <span className="template-side-field__label">{t("template.field.effectName")}</span>
              <div aria-label={t("template.field.effectName")} className="template-effect-grid" role="group">
                {effects.map((effect) => {
                  const isSelected = selectedEffectNames.has(effect.name);
                  return (
                    <button
                      aria-pressed={isSelected}
                      className={`template-character-card${isSelected ? " template-character-card--selected" : ""}`}
                      key={effect.name}
                      onClick={() => toggleEffect(effect.name, !isSelected)}
                      style={{ "--template-character-color": effect.color || "#5b8def" } as CSSProperties}
                      title={effect.name}
                      type="button"
                    >
                      <span aria-hidden className="template-character-card__dot" />
                      <span className="template-character-card__name">{effect.name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          <div className="template-side-field" data-standalone-gpu="true">
            <div className="template-sprite-heading">
              <label className="template-side-field__label" htmlFor="template-use-cg">
                {t("template.field.useCg")}
              </label>
              <Switch checked={useCg} id="template-use-cg" onChange={(event) => setUseCg(event.target.checked)} />
            </div>
          </div>

          <div className="template-side-field">
            <span className="template-side-field__label">{t("template.field.voiceLanguage")}</span>
            <div className="template-language-segments" role="group">
              {voiceLanguages.map((option) => (
                <button
                  aria-pressed={voiceLanguage === option.value}
                  className={`template-language-segment${
                    voiceLanguage === option.value ? " template-language-segment--active" : ""
                  }`}
                  key={option.value}
                  onClick={() => handleVoiceLanguageChange(option.value)}
                  type="button"
                >
                  {t(option.labelKey)}
                </button>
              ))}
            </div>
          </div>

          <div className="template-runtime-fields">
            <label className="template-side-field" data-standalone-gpu="true">
              <span className="template-side-field__label">{t("chat.memoryMode.label")}</span>
              <Select
                aria-label={t("chat.memoryMode.label")}
                onChange={(event) => setMemoryMode(event.target.value as MemoryMode)}
                value={memoryMode}
              >
                <option value="isolated">{t("chat.memoryMode.isolated")}</option>
                <option value="shared">{t("chat.memoryMode.shared")}</option>
                <option value="inherit_readonly">{t("chat.memoryMode.inheritReadonly")}</option>
              </Select>
              <span className="template-options-panel__hint">
                {t(
                  memoryMode === "shared"
                    ? "chat.memoryMode.sharedHint"
                    : memoryMode === "inherit_readonly"
                      ? "chat.memoryMode.inheritReadonlyHint"
                      : "chat.memoryMode.isolatedHint",
                )}
              </span>
            </label>
            <div className="template-side-field">
              <div className="template-sprite-heading">
                <label className="template-side-field__label" htmlFor="template-auto-outfit-switch">
                  {t("launch.autoOutfitSwitch")}
                </label>
                <Switch
                  aria-label={t("launch.autoOutfitSwitch")}
                  checked={autoOutfitSwitch}
                  id="template-auto-outfit-switch"
                  onChange={(event) => setAutoOutfitSwitch(event.currentTarget.checked)}
                />
              </div>
            </div>
            {selectedCharacterRecords
              .map((character) => ({ character, groups: characterOutfitGroups(character) }))
              .filter(({ groups }) => groups.length > 1)
              .map(({ character, groups }) => (
                <label className="template-side-field" key={character.name}>
                  <span className="template-side-field__label">
                    {t("launch.initialOutfits")} · {character.name}
                  </span>
                  <Select
                    aria-label={`${t("launch.initialOutfits")} · ${character.name}`}
                    onChange={(event) =>
                      setInitialOutfits((current) => {
                        const next = { ...current };
                        if (event.target.value) {
                          next[character.name] = event.target.value;
                        } else {
                          delete next[character.name];
                        }
                        return next;
                      })
                    }
                    value={initialOutfits[character.name] ?? ""}
                  >
                    <option value="">{t("launch.initialOutfitDefault")}</option>
                    {groups.map((group) => (
                      <option key={group} value={group}>
                        {group}
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
            <div className="template-side-field">
              <div className="template-sprite-heading">
                <label className="template-side-field__label" htmlFor="template-initial-sprite">
                  {t("template.field.initSprite")}
                </label>
                <Switch
                  aria-label={t("template.field.showInitialSprite")}
                  checked={showInitialSprite}
                  onChange={(event) => setShowInitialSprite(event.target.checked)}
                  title={t("template.field.showInitialSprite")}
                />
              </div>
              <FilePicker
                acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
                disabled={!showInitialSprite}
                id="template-initial-sprite"
                onChange={(event) => setInitSpritePath(event.target.value)}
                onPathChange={setInitSpritePath}
                pickLabel={t("common.chooseFile")}
                pickerTitle={t("template.field.initSprite")}
                readOnly={false}
                value={initSpritePath}
              />
            </div>
            {!createOnly && !conversationId && (
              <label className="template-side-field">
                <span className="template-side-field__label">{t("template.field.historyFile")}</span>
                <TextInput onChange={(event) => setHistoryPath(event.target.value)} value={historyPath} />
              </label>
            )}
          </div>
        </aside>
      </div>

      <footer
        className={`template-page__footer${createOnly || conversationId ? " template-page__footer--single" : ""}`}
      >
        <AsyncButton
          disabled={
            !sessionRestored || runtimeClosing || (!conversationId && runtimeLaunchDisabled) || initializationPending
          }
          icon={<Play aria-hidden className="button__icon" />}
          loading={launchMutation.isPending}
          onClick={() => handleLaunch(false)}
          variant="primary"
        >
          {t(
            conversationId
              ? "conversation.saveAndContinue"
              : createOnly
                ? "conversation.createAndStart"
                : "template.action.launch",
          )}
        </AsyncButton>
        {!createOnly && !conversationId && (
          <Button
            disabled={!sessionRestored || runtimeLaunchDisabled || initializationPending}
            icon={<RotateCw aria-hidden className="button__icon" />}
            onClick={() => setQuickRestartOpen(true)}
            variant="ghost"
          >
            {t("template.action.quickRestart")}
          </Button>
        )}
      </footer>

      <CharacterConfigDialog
        allowPlayerDialogue={allowPlayerDialogue}
        characterPromptMode={characterPromptMode}
        characters={characters}
        error={characterDialogError}
        onClose={() => setCharacterDialogOpen(false)}
        onConfirm={confirmCharacterConfig}
        open={characterDialogOpen}
        pending={ensureBriefsMutation.isPending}
        playerCharacter={effectivePlayerCharacter}
        primaryCharacters={primaryCharacters}
        readPlayerSpeech={readPlayerSpeech}
        selectedCharacters={selectedCharacters}
      />

      <UserPromptPresetsDialog
        appliedPresets={appliedPresetsSnapshot}
        baseScenario={baseScenario}
        library={presetsLibrary}
        libraryError={presetsQuery.isError ? t("template.presets.loadFailed") : ""}
        libraryLoading={presetsQuery.isPending}
        libraryReady={presetsLibraryReady}
        onClose={() => setUserPromptDialogOpen(false)}
        onConfirm={handleConfirmUserPrompt}
        onRetryLibrary={() => void presetsQuery.refetch()}
        onSaveLibrary={(nextLibrary) => savePresetsMutation.mutateAsync(nextLibrary)}
        open={userPromptDialogOpen}
        savingLibrary={savePresetsMutation.isPending}
        selectedPresetIds={draft.selectedPresetIds ?? []}
      />

      <SystemPromptDialog
        canAutoSync={selectedCharacters.length > 0 && (selectedCharacters.length <= 4 || Boolean(characterPromptMode))}
        generating={generateMutation.isPending}
        onClose={() => setSystemPromptDialogOpen(false)}
        onConfirm={handleConfirmSystemPrompt}
        onRegenerate={handleRegenerateFromDialog}
        open={systemPromptDialogOpen}
        rules={{
          maxDialogItems,
          maxSpeechChars,
          mediaSelectionMode,
          useChoice,
          useCot,
          useEffectPrompt,
          useNarration,
          useStat,
          useTranslation,
        }}
        systemConfigStale={systemConfigStale}
        systemManuallyEdited={systemManuallyEdited}
        systemText={draft.system ?? ""}
      />

      <AlertDialog
        body={t("template.quickRestart.body")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("template.action.quickRestart")}
        onCancel={() => setQuickRestartOpen(false)}
        onConfirm={() => {
          setQuickRestartOpen(false);
          handleLaunch(true);
        }}
        open={quickRestartOpen}
        title={t("template.quickRestart.title")}
      />
      <PrimaryCharacterDialog
        characters={selectedCharacterRecords.filter((character) => character.name !== effectivePlayerCharacter)}
        initialPrimaryCharacters={primaryCharacters}
        onConfirm={(names) => void confirmPrimaryCharacters(names)}
        onUseAll={useAllCharactersAsPrimary}
        open={primaryCharacterDialogOpen}
        pending={ensureBriefsMutation.isPending}
      />
      <ChatInitializationDialog
        error={initializationError}
        onClose={closeInitialization}
        open={!initializationService && initializationOpen}
        pending={initializationPending}
        task={initializationTask}
      />
      <MobileAccessDialog
        info={mobileAccessInfo}
        onClose={() => setMobileAccessInfo(null)}
        onOpenLocalChat={() => {
          const info = mobileAccessInfo;
          setMobileAccessInfo(null);
          return showChatSurface({ snapshot: info ? { runtimeMode: "react", wsUrl: info.websocketUrl } : null });
        }}
      />
    </div>
  );
}
