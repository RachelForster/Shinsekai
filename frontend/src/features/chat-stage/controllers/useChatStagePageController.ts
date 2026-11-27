import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { isTauriDesktop } from "../../../shared/desktop/desktopApi";
import { useI18n } from "../../../shared/i18n";
import {
  getRuntimeTarget,
  isStandaloneRuntimeActive,
  RUNTIME_MODE_CHANGE_EVENT,
} from "../../../shared/platform/runtimeTarget";
import { useToast } from "../../../shared/ui";
import { buildChatStageViewModel, chatStageReducer } from "../chatState";
import { isRemoteMobileAccessPage } from "../chatStageUtils";
import { shouldApplyVnDialogAdaptation } from "../dialogViewportLayout";
import { useChatStageCommands } from "../hooks/useChatStageCommands";
import { useStageViewport } from "../hooks/useStageViewport";
import { chatStageRuntimeStyle } from "../runtimeConfig";
import { limitChatStageSpritesToSlots } from "../state/sprites";
import { initialChatStageState } from "./chatStageRouteState";
import { useChatStageDesktopWindowController } from "./useChatStageDesktopWindowController";
import { useChatStageHistoryReplayController } from "./useChatStageHistoryReplayController";
import { useChatStageInteractionController } from "./useChatStageInteractionController";
import { useChatStagePluginOverlayController } from "./useChatStagePluginOverlayController";
import { useChatStageRuntimeConfigController } from "./useChatStageRuntimeConfigController";
import { useChatStageScreenShareController } from "./useChatStageScreenShareController";

export function useChatStagePageController() {
  const location = useLocation();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { t } = useI18n();
  const [state, dispatch] = useReducer(chatStageReducer, location.state, initialChatStageState);
  const viewModel = useMemo(() => buildChatStageViewModel(state), [state]);

  const [confirmClearHistory, setConfirmClearHistory] = useState(false);
  const [conversationEditorOpen, setConversationEditorOpen] = useState(false);
  const [runtimeModeOpen, setRuntimeModeOpen] = useState(false);
  const [dialogControlsLocked, setDialogControlsLocked] = useState(false);
  const [themePickerOpen, setThemePickerOpen] = useState(false);
  const [tokenUsageOpen, setTokenUsageOpen] = useState(false);
  const [toolbarConfigOpen, setToolbarConfigOpen] = useState(false);
  const dialogToolbarLayerRef = useRef<HTMLDivElement>(null);

  const remoteMobileAccess = isRemoteMobileAccessPage();
  const [standalone, setStandalone] = useState(() => isStandaloneRuntimeActive());
  useEffect(() => {
    const updateStandalone = () => setStandalone(isStandaloneRuntimeActive());
    window.addEventListener(RUNTIME_MODE_CHANGE_EVENT, updateStandalone);
    window.addEventListener("storage", updateStandalone);
    return () => {
      window.removeEventListener(RUNTIME_MODE_CHANGE_EVENT, updateStandalone);
      window.removeEventListener("storage", updateStandalone);
    };
  }, []);

  const stageSprites = useMemo(
    () => (remoteMobileAccess ? limitChatStageSpritesToSlots(viewModel.sprites, 1) : viewModel.sprites),
    [remoteMobileAccess, viewModel.sprites],
  );
  const desktopApp = isTauriDesktop();
  const standaloneDesktopWindow = desktopApp && location.pathname === "/chat-stage";

  const commands = useChatStageCommands({
    confirmClearHistory,
    dispatch,
    operationFailedTitle: t("common.operationFailed"),
    setConfirmClearHistory,
    showToast,
    t,
  });

  const runtime = useChatStageRuntimeConfigController({
    sendCommand: commands.sendCommand,
  });

  const historyReplay = useChatStageHistoryReplayController({
    dispatch,
    refreshHistory: commands.refreshHistory,
    sendCommand: commands.sendCommand,
    setAuto: runtime.setAuto,
    showToast,
    state,
    t,
    viewModel,
  });

  const pluginOverlay = useChatStagePluginOverlayController({
    inputAttachments: state.inputAttachments,
    inputDraft: state.inputDraft,
    location,
    navigate,
    pluginPagePresentations: state.pluginPagePresentations,
    sendCommand: commands.sendCommand,
  });

  const screenShare = useChatStageScreenShareController({
    characterAudioPlaying: viewModel.status === "speaking" || viewModel.status === "replaying",
    perception: state.perception,
    perceptionCaptureRequestSeq: state.perceptionCaptureRequestSeq,
    sessionClosed: Boolean(state.sessionClosedReason),
    showToast,
    t,
  });

  const miniAvatarActive =
    runtime.runtimeConfig.miniAvatarMode && !historyReplay.activeReplay && !state.replay && !remoteMobileAccess;
  const transparentBackground = miniAvatarActive || !viewModel.backgroundPath;
  const statsVisible = viewModel.stats.length > 0;
  const tokenUsageVisible = tokenUsageOpen && Boolean(viewModel.tokenUsageText);
  const modalOpen =
    historyReplay.activeReplay != null ||
    state.replay != null ||
    conversationEditorOpen ||
    pluginOverlay.overlayTarget != null ||
    themePickerOpen ||
    toolbarConfigOpen ||
    screenShare.screenSettingsOpen ||
    screenShare.screenSharePreflightOpen ||
    historyReplay.historyDialogOpen ||
    historyReplay.historyExport != null ||
    confirmClearHistory ||
    historyReplay.confirmRevertUserIndex != null;
  const dialogSurfaceVisible =
    Boolean(historyReplay.activeReplay) || viewModel.layers.dialog || viewModel.layers.options;

  const interaction = useChatStageInteractionController({
    activeReplay: historyReplay.activeReplay,
    auto: runtime.runtimeConfig.auto,
    dialogTextDirection: runtime.dialogTextDirection,
    dispatch,
    exitCg: historyReplay.exitCg,
    historyDialogOpen: historyReplay.historyDialogOpen,
    longPressTalk: runtime.runtimeConfig.longPressTalk,
    miniAvatarActive,
    modalOpen,
    sendCommand: commands.sendCommand,
    showToast,
    state,
    t,
    toggleAuto: runtime.toggleAuto,
    typewriterCps: runtime.typewriterCps,
    viewModel,
  });

  const { setHistoryDialogOpen } = historyReplay;
  const { setScreenSettingsOpen, setScreenSharePreflightOpen } = screenShare;
  const closeModalsForMiniAvatar = useCallback(() => {
    setThemePickerOpen(false);
    setTokenUsageOpen(false);
    setToolbarConfigOpen(false);
    setHistoryDialogOpen(false);
    setScreenSettingsOpen(false);
    setScreenSharePreflightOpen(false);
    setConversationEditorOpen(false);
  }, [setHistoryDialogOpen, setScreenSettingsOpen, setScreenSharePreflightOpen]);

  const desktop = useChatStageDesktopWindowController({
    activeReplay: historyReplay.activeReplay,
    alwaysOnTop: runtime.runtimeConfig.alwaysOnTop,
    cgVisible: viewModel.layers.cg,
    desktopApp,
    miniAvatarActive,
    modalOpen,
    navigate,
    onBeforeEnterMiniAvatar: closeModalsForMiniAvatar,
    remoteMobileAccess,
    setRuntimeConfig: runtime.setRuntimeConfig,
    standaloneDesktopWindow,
    state,
    transparentBackground,
  });

  const stageViewport = useStageViewport(interaction.stageRef);
  const activeStageViewport = miniAvatarActive ? null : stageViewport;
  const vnDialogActive = shouldApplyVnDialogAdaptation(activeStageViewport);
  const stageStyle = useMemo(
    () => chatStageRuntimeStyle(runtime.runtimeConfig, runtime.themeStyle, runtime.mainThemeColor, activeStageViewport),
    [activeStageViewport, runtime.mainThemeColor, runtime.runtimeConfig, runtime.themeStyle],
  );

  useEffect(() => {
    if (!viewModel.layers.dialog) {
      setToolbarConfigOpen(false);
    }
  }, [viewModel.layers.dialog]);

  useEffect(() => {
    if (!viewModel.tokenUsageText) {
      setTokenUsageOpen(false);
    }
  }, [viewModel.tokenUsageText]);

  useLayoutEffect(() => {
    const toolbar = dialogToolbarLayerRef.current;
    const stage = toolbar?.parentElement;
    if (
      !toolbar ||
      !stage ||
      !dialogSurfaceVisible ||
      miniAvatarActive ||
      historyReplay.activeReplay ||
      runtime.dialogToolbarPlacement !== "input"
    ) {
      return;
    }

    // Keep the dialog stack clear of the detached input toolbar.
    const updateClearance = () => {
      const { height } = toolbar.getBoundingClientRect();
      stage.style.setProperty(
        "--chat-dialog-toolbar-clearance",
        `calc(var(--chat-dialog-toolbar-layer-bottom) + ${height}px + var(--chat-dialog-toolbar-gap))`,
      );
    };
    updateClearance();
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(updateClearance);
    observer?.observe(toolbar);
    return () => {
      observer?.disconnect();
      stage.style.removeProperty("--chat-dialog-toolbar-clearance");
    };
  }, [
    dialogSurfaceVisible,
    historyReplay.activeReplay,
    miniAvatarActive,
    runtime.dialogToolbarPlacement,
    runtime.runtimeConfig.windowScale,
    stageViewport.height,
    stageViewport.width,
  ]);

  const replayDisabled =
    Boolean(state.sessionClosedReason) ||
    ["generating", "streaming", "speaking", "initializing"].includes(viewModel.status) ||
    viewModel.asrRunning ||
    Boolean(viewModel.toolConfirmation) ||
    state.turnState.pendingCount > 0 ||
    interaction.attachmentUploadPending;

  const openWorkspace = useCallback(() => {
    navigate(getRuntimeTarget() === "toy" ? "/settings/characters" : "/settings/templates");
  }, [navigate]);

  return {
    commands,
    desktop,
    historyReplay,
    interaction,
    modals: {
      confirmClearHistory,
      conversationEditorOpen,
      dialogControlsLocked,
      runtimeModeOpen,
      setConfirmClearHistory,
      setConversationEditorOpen,
      setDialogControlsLocked,
      setRuntimeModeOpen,
      setThemePickerOpen,
      setTokenUsageOpen,
      setToolbarConfigOpen,
      themePickerOpen,
      tokenUsageOpen,
      toolbarConfigOpen,
    },
    pluginOverlay,
    runtime,
    screenShare,
    stage: {
      dialogSurfaceVisible,
      dialogToolbarLayerRef,
      miniAvatarActive,
      modalOpen,
      openWorkspace,
      remoteMobileAccess,
      replayDisabled,
      stageSprites,
      stageStyle,
      standalone,
      statsVisible,
      tokenUsageVisible,
      transparentBackground,
      vnDialogActive,
    },
    state,
    viewModel,
  };
}

export type ChatStagePageController = ReturnType<typeof useChatStagePageController>;
