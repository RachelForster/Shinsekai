import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { charactersQueryKey, ensureCharacterBriefs } from "../../../entities/character/repository";
import { resolveConversationTitle } from "../../../entities/chat/conversationTitle";
import {
  conversationsQueryKey,
  installMissingRuntimeDependency,
  launchChat,
  reconfigureConversation,
} from "../../../entities/chat/repository";
import { getAppConfig, saveSystemConfig } from "../../../entities/config/repository";
import {
  saveTemplate,
  saveTemplateSession,
  templatesQueryKey,
  type TemplateSummary,
} from "../../../entities/template/repository";
import { showChatSurface } from "../../../shared/desktop/chatWindow";
import { useI18n } from "../../../shared/i18n";
import type {
  ChatSnapshot,
  InitialOutfitValue,
  MobileAccessInfo,
  TemplateLaunchSession,
} from "../../../shared/platform/types";
import { useToast } from "../../../shared/ui";
import { compatibleInitialSpritePath } from "../../chat-startup/initialSpriteSelection";
import { useChatInitialization, type ChatInitializationService } from "../../chat-startup/useChatInitialization";
import { useChatLaunchGuard } from "../../chat-startup/useChatLaunchGuard";
import { characterOutfitGroups, type TemplateEditorPageProps } from "../templateContext";
import type { CharacterConfigCommit } from "../CharacterConfigDialog";
import {
  buildChatLaunchPayload,
  buildTemplateLaunchSession,
  buildTemplateSummary,
  normalizeTemplateSummary,
  synchronizeChatLaunchPayloadWithSession,
  synchronizeTemplateLaunchSessionWithSnapshot,
} from "../templateFlow";
import type { useTemplateGenerationController } from "./useTemplateGenerationController";
import type { TemplateSessionState } from "./useTemplateSessionState";

interface UseTemplateLaunchControllerOptions {
  generation: ReturnType<typeof useTemplateGenerationController>;
  initializationService?: ChatInitializationService;
  props: Pick<
    TemplateEditorPageProps,
    "conversationId" | "conversationTitle" | "createOnly" | "onApplied" | "onLaunchStarted" | "onPendingChange"
  >;
  state: TemplateSessionState;
}

export function useTemplateLaunchController({
  generation,
  initializationService,
  props,
  state,
}: UseTemplateLaunchControllerOptions) {
  const { conversationId, conversationTitle, createOnly = false, onApplied, onLaunchStarted, onPendingChange } = props;
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const [quickRestartOpen, setQuickRestartOpen] = useState(false);
  const [mobileAccessInfo, setMobileAccessInfo] = useState<MobileAccessInfo | null>(null);

  const { refreshRuntimeStatus, runtimeLaunchDisabled, runtimeClosing, updateRuntimeStatusFromSnapshot } =
    useChatLaunchGuard();
  const localInitialization = useChatInitialization();
  const initialization = initializationService ?? localInitialization;
  const { initializationPending, runChatInitialization } = initialization;
  useEffect(() => onPendingChange?.(initializationPending), [initializationPending, onPendingChange]);

  const validateName = () => {
    if (!state.draft.name.trim()) {
      state.setNameError(t("template.validation.nameRequired"));
      return false;
    }
    state.setNameError("");
    return true;
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

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!validateName()) {
        throw new Error(t("template.validation.nameRequired"));
      }
      return saveTemplate({
        ...buildTemplateSummary(state.effectiveSummaryDraft()),
        ...state.templatePlayerOptions,
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
      state.setIsCreating(false);
      state.setSessionDraftActive(false);
      state.setDraft(normalized);
      state.setSelectedId(normalized.id);
      showToast({ kind: "success", title: t("template.toast.saved") });
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
          state.setHistoryPath(confirmedSession.historyPath);
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
      state.setSessionDraftActive(true);
      state.setDraft(normalized);
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
    const summaryDraft = state.effectiveSummaryDraft();
    const template = {
      ...buildTemplateSummary(summaryDraft),
      ...state.templatePlayerOptions,
    };
    const filteredInitialOutfits: Record<string, InitialOutfitValue> = {};
    for (const character of state.selectedCharacterRecords) {
      const chosen = state.initialOutfits[character.name]?.trim();
      if (chosen && characterOutfitGroups(character).includes(chosen)) {
        filteredInitialOutfits[character.name] = chosen;
      }
    }
    const session: TemplateLaunchSession = buildTemplateLaunchSession({
      appliedPresets: state.appliedPresetsSnapshot,
      autoOutfitSwitch: state.autoOutfitSwitch,
      backgroundName: state.selectedBackground,
      baseScenario: state.baseScenario,
      characterPromptMode: state.characterPromptMode ?? "full",
      draft: summaryDraft,
      effectNames: state.selectedEffects,
      initialOutfits: filteredInitialOutfits,
      memoryMode: state.memoryMode,
      mobileAccessEnabled: state.mobileAccessEnabled,
      mediaSelectionMode: state.mediaSelectionMode,
      options: state.templateOptionsState,
      primaryCharacters: state.characterPromptMode === "compact" ? state.primaryCharacters : state.selectedCharacters,
      ...state.playerOptions,
      runtime: createOnly ? { ...state.runtimeOptionsState, historyPath: "" } : state.runtimeOptionsState,
      selectedCharacters: state.selectedCharacters,
      selectedPresetIds: state.effectiveSelectedPresetIds,
      selectedTemplateId: state.selectedId,
      systemManuallyEdited: state.systemManuallyEdited,
    });
    launchMutation.mutate({ resetHistory, template, session });
  };

  useEffect(() => {
    if (state.launchReadyAfterRoleGeneration === null) {
      return;
    }
    const resetHistory = state.launchReadyAfterRoleGeneration;
    state.setLaunchReadyAfterRoleGeneration(null);
    launchCurrentDraft(resetHistory);
  }, [state.launchReadyAfterRoleGeneration]);

  const handleLaunch = (resetHistory: boolean) => {
    if (state.selectedCharacters.length > 4 && !state.characterPromptMode) {
      state.deferredLaunchRef.current = resetHistory;
      state.setPrimaryCharacterDialogOpen(true);
      return;
    }
    // A new chat may reuse a semantic or background-bound session draft while
    // defaulting to indexed selection and a transparent background. Regenerate
    // its instructions before starting that chat.
    if (
      !state.systemManuallyEdited &&
      (state.draft.mediaSelectionMode !== state.mediaSelectionMode ||
        (state.restoredSessionBackgroundRef.current !== null &&
          state.restoredSessionBackgroundRef.current !== state.selectedBackground))
    ) {
      state.restoredSessionBackgroundRef.current = null;
      state.deferredLaunchRef.current = resetHistory;
      const nextBase = state.scenarioForSelectedCharacters();
      generation.generateMutation.mutate({
        input: generation.generationInput(nextBase),
        meta: {
          appliedPresets: state.appliedPresetsSnapshot,
          baseScenario: nextBase,
          selectedPresetIds: state.effectiveSelectedPresetIds,
        },
        silent: true,
      });
      return;
    }
    launchCurrentDraft(resetHistory);
  };

  const confirmCharacterConfig = async (next: CharacterConfigCommit) => {
    state.setCharacterDialogError("");
    const effectivePlayer = next.selectedCharacters.includes(next.playerCharacter) ? next.playerCharacter : "";
    const resolvedMode = next.characterPromptMode;
    let resolvedPrimary = next.primaryCharacters;

    if (resolvedMode === "compact") {
      const secondary = next.selectedCharacters.filter(
        (name) => name !== effectivePlayer && !resolvedPrimary.includes(name),
      );
      try {
        const result = await ensureBriefsMutation.mutateAsync(secondary);
        if (result.characters.length) {
          const updated = new Map(result.characters.map((character) => [character.name, character]));
          queryClient.setQueryData(charactersQueryKey, (current: typeof state.characters = []) =>
            current.map((character) => updated.get(character.name) ?? character),
          );
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : t("character.error.aiFallback");
        state.setCharacterDialogError(message);
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

    state.setSelectedCharacters(next.selectedCharacters);
    state.setCharacterPromptMode(resolvedMode);
    state.setPrimaryCharacters(resolvedPrimary);
    state.setPlayerCharacter(effectivePlayer);
    state.setReadPlayerSpeech(Boolean(effectivePlayer && next.readPlayerSpeech));
    state.setAllowPlayerDialogue(next.allowPlayerDialogue);
    state.setInitSpritePath((path) =>
      compatibleInitialSpritePath({
        characters: state.characters,
        path,
        preserveUnknown: false,
        selectedCharacters: next.selectedCharacters,
      }),
    );
    state.setCharacterDialogOpen(false);
  };

  const useAllCharactersAsPrimary = () => {
    state.setPrimaryCharacters(state.selectedCharacters);
    state.setCharacterPromptMode("full");
    state.setPrimaryCharacterDialogOpen(false);
  };

  const confirmPrimaryCharacters = async (nextPrimaryCharacters: string[]) => {
    const primary = nextPrimaryCharacters.filter((name) => state.selectedCharacters.includes(name));
    const secondary = state.selectedCharacters.filter(
      (name) => name !== state.effectivePlayerCharacter && !primary.includes(name),
    );
    try {
      const result = await ensureBriefsMutation.mutateAsync(secondary);
      if (result.characters.length) {
        const updated = new Map(result.characters.map((character) => [character.name, character]));
        queryClient.setQueryData(charactersQueryKey, (current: typeof state.characters = []) =>
          current.map((character) => updated.get(character.name) ?? character),
        );
      }
      state.setPrimaryCharacters(primary);
      state.setCharacterPromptMode("compact");
      state.setPrimaryCharacterDialogOpen(false);
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.aiFallback"),
        title: t("template.primaryCharacters.title"),
      });
    }
  };

  const handleVoiceLanguageChange = (nextLanguage: string) => {
    if (nextLanguage === state.voiceLanguage) {
      return;
    }
    state.setVoiceLanguage(nextLanguage);
    voiceLanguageMutation.mutate(nextLanguage);
  };

  return {
    confirmCharacterConfig,
    confirmPrimaryCharacters,
    ensureBriefsMutation,
    handleLaunch,
    handleVoiceLanguageChange,
    initialization,
    launchMutation,
    mobileAccessInfo,
    quickRestartOpen,
    runtimeClosing,
    runtimeLaunchDisabled,
    saveMutation,
    setMobileAccessInfo,
    setQuickRestartOpen,
    useAllCharactersAsPrimary,
  };
}
