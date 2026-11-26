import { showChatSurface } from "../../../shared/desktop/chatWindow";
import { useI18n } from "../../../shared/i18n";
import { MAX_VISIBLE_PRESET_CHIPS, type TemplateEditorContext, type TemplateEditorPageProps } from "../templateContext";
import { buildDefaultTemplateScenario } from "../templateFlow";
import { useTemplateGenerationController } from "./useTemplateGenerationController";
import { useTemplateLaunchController } from "./useTemplateLaunchController";
import { useTemplateSessionState } from "./useTemplateSessionState";

export type { TemplateEditorContext, TemplateEditorPageProps } from "../templateContext";

export function useTemplateEditorController(props: TemplateEditorPageProps): TemplateEditorContext {
  const { conversationId, createOnly = false, initializationService } = props;
  const { t } = useI18n();
  const state = useTemplateSessionState({ conversationId, createOnly });
  const generation = useTemplateGenerationController(state);
  const launch = useTemplateLaunchController({
    generation,
    initializationService,
    props,
    state,
  });

  const npcCount = state.selectedCharacters.filter((name) => name !== state.effectivePlayerCharacter).length;
  const primaryCount =
    state.characterPromptMode === "full"
      ? npcCount
      : state.primaryCharacters.filter((name) => name !== state.effectivePlayerCharacter).length;
  const showRoleSummary = npcCount > 4 || (npcCount > 0 && Boolean(state.effectivePlayerCharacter));
  const roleSummaryText =
    state.characterPromptMode === "full"
      ? t("template.primaryCharacters.statusFull", { count: npcCount })
      : state.characterPromptMode === "compact"
        ? t("template.primaryCharacters.statusCompact", {
            primary: Math.min(primaryCount, npcCount),
            secondary: Math.max(0, npcCount - Math.min(primaryCount, npcCount)),
          })
        : t("template.primaryCharacters.statusPending", { count: npcCount });

  const defaultScenarioText = buildDefaultTemplateScenario(state.selectedCharacters, t("template.defaultScenario"));
  const scenarioStatusKey = !state.baseScenario.trim()
    ? ("template.bar.scenarioEmpty" as const)
    : defaultScenarioText && state.baseScenario === defaultScenarioText
      ? ("template.bar.scenarioDefault" as const)
      : ("template.bar.scenarioCustom" as const);

  const visiblePresetChips = state.resolvedSelectedPresets.slice(0, MAX_VISIBLE_PRESET_CHIPS);
  const hiddenPresetCount = Math.max(0, state.resolvedSelectedPresets.length - visiblePresetChips.length);

  const systemConfigStale = state.systemManuallyEdited && state.fullSystemSyncKey !== state.manualBaseKey;
  const enabledRulesCount = [
    state.useEffectPrompt,
    state.useTranslation,
    state.useCot,
    state.useChoice,
    state.useNarration,
    state.useStat,
  ].filter(Boolean).length;
  const systemStatusPill = state.systemManuallyEdited
    ? {
        className: systemConfigStale ? "is-warning" : "is-manual",
        label: t(systemConfigStale ? "template.bar.systemManualStale" : "template.bar.systemManual"),
      }
    : state.selectedCharacters.length === 0 && !String(state.draft.system ?? "").trim()
      ? { className: "is-pending", label: t("template.bar.systemPendingCharacters") }
      : { className: "is-auto", label: t("template.bar.systemAuto") };

  return {
    allowPlayerDialogue: state.allowPlayerDialogue,
    appliedPresetsSnapshot: state.appliedPresetsSnapshot,
    autoOutfitSwitch: state.autoOutfitSwitch,
    backgroundOptions: state.backgroundOptions,
    baseScenario: state.baseScenario,
    characterByName: state.characterByName,
    characterDialogError: state.characterDialogError,
    characterDialogOpen: state.characterDialogOpen,
    characterPromptMode: state.characterPromptMode,
    characters: state.characters,
    closeInitialization: launch.initialization.closeInitialization,
    closeMobileAccess: () => launch.setMobileAccessInfo(null),
    confirmCharacterConfig: launch.confirmCharacterConfig,
    confirmPrimaryCharacters: launch.confirmPrimaryCharacters,
    conversationId,
    createOnly,
    dialogFormats: state.dialogFormats,
    draft: state.draft,
    effectivePlayerCharacter: state.effectivePlayerCharacter,
    effects: state.effects,
    enabledRulesCount,
    ensureBriefsPending: launch.ensureBriefsMutation.isPending,
    failedQuery: state.failedQuery,
    generatePending: generation.generateMutation.isPending,
    handleConfirmSystemPrompt: generation.handleConfirmSystemPrompt,
    handleConfirmUserPrompt: generation.handleConfirmUserPrompt,
    handleLaunch: launch.handleLaunch,
    handleRegenerateFromDialog: generation.handleRegenerateFromDialog,
    handleTemplateSelect: (nextId: string) => {
      if (!nextId) {
        return;
      }
      state.restoredSessionBackgroundRef.current = null;
      state.setSessionDraftActive(false);
      state.setIsCreating(false);
      state.setSelectedId(nextId);
    },
    handleVoiceLanguageChange: launch.handleVoiceLanguageChange,
    hiddenPresetCount,
    historyPath: state.historyPath,
    initializationError: launch.initialization.initializationError,
    initializationOpen: launch.initialization.initializationOpen,
    initializationPending: launch.initialization.initializationPending,
    initializationServiceProvided: Boolean(initializationService),
    initializationTask: launch.initialization.initializationTask,
    initialOutfits: state.initialOutfits,
    initSpritePath: state.initSpritePath,
    isCreating: state.isCreating,
    isLoading: state.isLoading,
    launchPending: launch.launchMutation.isPending,
    maxDialogItems: state.maxDialogItems,
    maxSpeechChars: state.maxSpeechChars,
    mediaSelectionMode: state.mediaSelectionMode,
    memoryMode: state.memoryMode,
    mobileAccessInfo: launch.mobileAccessInfo,
    nameError: state.nameError,
    openCharacterDialog: () => {
      state.setCharacterDialogError("");
      state.setCharacterDialogOpen(true);
    },
    openLocalChatFromMobile: () => {
      const info = launch.mobileAccessInfo;
      launch.setMobileAccessInfo(null);
      return showChatSurface({ snapshot: info ? { runtimeMode: "react", wsUrl: info.websocketUrl } : null });
    },
    outputFormat: state.outputFormat,
    playerCharacter: state.playerCharacter,
    presetsLibrary: state.presetsLibrary,
    presetsLibraryError: state.presetsIsError,
    presetsLibraryPending: state.presetsPending,
    presetsLibraryReady: state.presetsLibraryReady,
    primaryCharacterDialogOpen: state.primaryCharacterDialogOpen,
    primaryCharacters: state.primaryCharacters,
    quickRestartOpen: launch.quickRestartOpen,
    readPlayerSpeech: state.readPlayerSpeech,
    resolvedSelectedPresets: state.resolvedSelectedPresets,
    restoreDefaultScenario: () => {
      const fallback =
        buildDefaultTemplateScenario(state.selectedCharacters, t("template.defaultScenario")) ||
        t("template.defaultScenario");
      state.setSessionDraftActive(true);
      state.updateDraft({ baseScenario: fallback });
    },
    retryPresetsLibrary: () => void state.refetchPresets(),
    roleSummaryText,
    runtimeClosing: launch.runtimeClosing,
    runtimeLaunchDisabled: launch.runtimeLaunchDisabled,
    saveLibraryPresets: (nextLibrary) => generation.savePresetsMutation.mutateAsync(nextLibrary),
    savePending: launch.saveMutation.isPending,
    savePresetsPending: generation.savePresetsMutation.isPending,
    saveTemplate: () => launch.saveMutation.mutate(),
    scenarioStatusKey,
    selectedBackground: state.selectedBackground,
    selectedCharacterRecords: state.selectedCharacterRecords,
    selectedCharacters: state.selectedCharacters,
    selectedEffectNames: state.selectedEffectNames,
    sessionDraftActive: state.sessionDraftActive,
    sessionRestored: state.sessionRestored,
    setAutoOutfitSwitch: state.setAutoOutfitSwitch,
    setCharacterDialogOpen: state.setCharacterDialogOpen,
    setHistoryPath: state.setHistoryPath,
    setInitialOutfits: state.setInitialOutfits,
    setInitSpritePath: state.setInitSpritePath,
    setMemoryMode: state.setMemoryMode,
    setNameError: state.setNameError,
    setQuickRestartOpen: launch.setQuickRestartOpen,
    setSelectedBackground: state.setSelectedBackground,
    setSessionDraftActive: state.setSessionDraftActive,
    setShowInitialSprite: state.setShowInitialSprite,
    setSystemPromptDialogOpen: state.setSystemPromptDialogOpen,
    setUseCg: state.setUseCg,
    setUserPromptDialogOpen: state.setUserPromptDialogOpen,
    showInitialSprite: state.showInitialSprite,
    showRoleSummary,
    systemConfigStale,
    systemManuallyEdited: state.systemManuallyEdited,
    systemPromptDialogOpen: state.systemPromptDialogOpen,
    systemStatusPill,
    templateSelectValue: state.templateSelectValue,
    templates: state.templates,
    toggleEffect: (name: string, checked: boolean) => {
      state.setSelectedEffects((current) =>
        checked ? [...new Set([...current, name])] : current.filter((item) => item !== name),
      );
    },
    updateDraft: state.updateDraft,
    useAllCharactersAsPrimary: launch.useAllCharactersAsPrimary,
    useCg: state.useCg,
    useChoice: state.useChoice,
    useCot: state.useCot,
    useEffectPrompt: state.useEffectPrompt,
    useNarration: state.useNarration,
    userPromptDialogOpen: state.userPromptDialogOpen,
    useStat: state.useStat,
    useTranslation: state.useTranslation,
    visiblePresetChips,
    voiceLanguage: state.voiceLanguage,
  };
}
