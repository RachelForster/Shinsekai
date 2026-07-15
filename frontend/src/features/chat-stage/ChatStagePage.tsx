import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { isTauriDesktop } from "../../shared/desktop/desktopApi";
import { closeChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import { normalizeThemeColor } from "../../shared/theme/appTheme";
import { DEFAULT_TYPEWRITER_CPS } from "../../shared/theme/chatTheme";
import { AlertDialog, useToast } from "../../shared/ui";
import { VOSK_MODEL_PATH } from "../api-settings/apiSettingsUtils";
import { closeChatRuntime } from "../chat-startup/runtimeState";
import { ChatConfigDialog } from "./components/ChatConfigDialog";
import { ConversationTreeDialog } from "./components/ConversationTreeDialog";
import { DialogStageControls } from "./components/DialogStageControls";
import { HistoryDialog } from "./components/HistoryDialog";
import { InputLayer } from "./components/InputLayer";
import {
  BackgroundLayer,
  BusyLayer,
  CgLayer,
  DialogLayer,
  NotificationLayer,
  OptionsLayer,
  SpriteLayer,
  StandaloneDesktopResizeHandles,
  TokenUsageLayer,
} from "./components/StageLayers";
import { TopStageTools } from "./components/TopStageTools";
import "./chat-stage.css";
import { buildChatStageViewModel, chatStageReducer, emptyChatState } from "./chatState";
import { layerClassName } from "./chatStageUtils";
import { useChatStageCommands } from "./hooks/useChatStageCommands";
import { useChatStageEvents } from "./hooks/useChatStageEvents";
import { useChatStageKeyboardShortcuts } from "./hooks/useChatStageKeyboardShortcuts";
import { useDesktopClickThrough } from "./hooks/useDesktopClickThrough";
import { useDesktopWindowDrag } from "./hooks/useDesktopWindowDrag";
import { useDialogTypewriter } from "./hooks/useDialogTypewriter";
import { useMainThemeColor } from "./hooks/useMainThemeColor";
import { useVoskModelAvailability } from "./hooks/useVoskModelAvailability";
import {
  chatStageRuntimeStyle,
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
  readChatStageRuntimeConfig,
  runtimeSpriteScale,
  writeChatStageRuntimeConfig,
} from "./runtimeConfig";
import { useOptionalChatTheme } from "./theme/ChatThemeProvider";

export function ChatStagePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(chatStageReducer, emptyChatState);
  const [confirmClearHistory, setConfirmClearHistory] = useState(false);
  const [confirmRevertUserIndex, setConfirmRevertUserIndex] = useState<number | null>(null);
  const [branchDialogOpen, setBranchDialogOpen] = useState(false);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [dialogControlsLocked, setDialogControlsLocked] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState(readChatStageRuntimeConfig);
  const mainThemeColor = useMainThemeColor();
  const [themePickerOpen, setThemePickerOpen] = useState(false);
  const [tokenUsageOpen, setTokenUsageOpen] = useState(false);
  const [toolbarConfigOpen, setToolbarConfigOpen] = useState(false);
  const voskModelState = useVoskModelAvailability();
  const { showToast } = useToast();
  const { t } = useI18n();
  const theme = useOptionalChatTheme();
  const themeStyle = theme?.style ?? {};
  const stageStyle = useMemo(
    () => chatStageRuntimeStyle(runtimeConfig, themeStyle, mainThemeColor),
    [mainThemeColor, runtimeConfig, themeStyle],
  );
  const effectiveDialogText = useMemo(
    () =>
      effectiveChatStageTextStyle(
        runtimeConfig.dialogText,
        defaultChatStageRuntimeConfig.dialogText,
        themeStyle,
        "dialogText",
      ),
    [runtimeConfig.dialogText, themeStyle],
  );
  const effectiveNameText = useMemo(
    () =>
      effectiveChatStageTextStyle(
        runtimeConfig.nameText,
        defaultChatStageRuntimeConfig.nameText,
        themeStyle,
        "nameText",
      ),
    [runtimeConfig.nameText, themeStyle],
  );
  const viewModel = useMemo(() => buildChatStageViewModel(state), [state]);
  const standaloneDesktopWindow = isTauriDesktop() && location.pathname === "/chat-stage";
  const handleSpriteDragStart = useDesktopWindowDrag(standaloneDesktopWindow);
  const transparentBackground = !viewModel.backgroundPath;
  const tokenUsageVisible = tokenUsageOpen && Boolean(viewModel.tokenUsageText);
  const modalOpen =
    themePickerOpen ||
    toolbarConfigOpen ||
    branchDialogOpen ||
    historyDialogOpen ||
    confirmClearHistory ||
    confirmRevertUserIndex != null;
  const clickThroughEnabled = standaloneDesktopWindow && transparentBackground && !modalOpen;
  const dialogToolbarPlacement =
    typeof themeStyle["--chat-dialog-toolbar-placement"] === "string"
      ? themeStyle["--chat-dialog-toolbar-placement"]
      : "";
  const dialogToolbarDetached = dialogToolbarPlacement === "input" || dialogToolbarPlacement === "dialog-top";
  const dialogToolbarReveal = themeStyle["--chat-dialog-toolbar-reveal"] === "hover" ? "hover" : "always";
  const inputLayout = themeStyle["--chat-input-layout"] === "pill" ? "pill" : "default";
  const longPressTalkVisible = inputLayout === "pill";
  const longPressTalkEnabled = longPressTalkVisible && runtimeConfig.longPressTalk && voskModelState.available;
  const forkHistoryEnabled = state.experimentalFeatures?.forkHistory === true;
  const conversationTreeEnabled = state.experimentalFeatures?.conversationTree === true;
  const dialogTextDirection = effectiveDialogText.direction ?? "ltr";
  const typewriterCps = runtimeConfig.typewriterCps ?? theme?.resolved?.typewriter.cps ?? DEFAULT_TYPEWRITER_CPS;
  const { historyLoading, refreshHistory, sendCommand } = useChatStageCommands({
    confirmClearHistory,
    dispatch,
    operationFailedTitle: t("common.operationFailed"),
    setConfirmClearHistory,
    showToast,
    t,
  });
  const autoAdvanceDialog = useCallback(() => {
    void sendCommand({ type: "dialog-advance" });
  }, [sendCommand]);
  const {
    dialogTotalCharacters,
    displayedDialog,
    queueAnimatedDialog,
    showDialogImmediately,
    showFullDialog,
    typingDialog,
  } = useDialogTypewriter({
    auto: runtimeConfig.auto,
    characterName: viewModel.dialogCharacterName,
    dialogVisible: viewModel.layers.dialog,
    html: viewModel.dialogHtml,
    onAutoAdvance: autoAdvanceDialog,
    optionsVisible: viewModel.layers.options,
    status: viewModel.status,
    text: viewModel.dialogText,
    textDirection: dialogTextDirection,
    typewriterCps,
  });
  const {
    handleStageContextMenu,
    handleStageFocus,
    handleStagePointerDown,
    handleStagePointerLeave,
    handleStagePointerMove,
  } = useDesktopClickThrough({
    clickThroughEnabled,
    standaloneDesktopWindow,
    transparentBackground,
  });
  useChatStageEvents({
    dispatch,
    eventSeq: state.eventSeq,
    loadFallbackMessage: t("chat.error.loadFallback"),
    queueAnimatedDialog,
  });

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

  useEffect(() => {
    if (!conversationTreeEnabled) {
      setBranchDialogOpen(false);
    }
  }, [conversationTreeEnabled]);

  useEffect(() => {
    writeChatStageRuntimeConfig(runtimeConfig);
  }, [runtimeConfig]);

  useEffect(() => {
    if (!voskModelState.loading && !voskModelState.available && runtimeConfig.longPressTalk) {
      setRuntimeConfig((current) => (current.longPressTalk ? { ...current, longPressTalk: false } : current));
    }
  }, [runtimeConfig.longPressTalk, voskModelState.available, voskModelState.loading]);

  const submit = () => {
    const text = viewModel.inputDraft.trim();
    if (!text) {
      return;
    }
    showDialogImmediately();
    dispatch({ source: "send-message", text, type: "submitUserMessage" });
    void sendCommand({ payload: text, type: "send-message" });
  };

  const submitOption = (option: string) => {
    showDialogImmediately();
    dispatch({ source: "submit-option", text: option, type: "submitUserMessage" });
    void sendCommand({ payload: option, type: "submit-option" });
  };

  const updateRuntimeTextSpeed = (typewriterCps: number) => {
    setRuntimeConfig((current) => ({ ...current, typewriterCps }));
  };

  const updateRuntimeImmersiveMode = (immersiveMode: boolean) => {
    setRuntimeConfig((current) => ({ ...current, immersiveMode }));
  };

  const updateRuntimeAutoHideTopTools = (autoHideTopTools: boolean) => {
    setRuntimeConfig((current) => ({ ...current, autoHideTopTools }));
  };

  const updateRuntimeAutoHideInput = (autoHideInput: boolean) => {
    setRuntimeConfig((current) => ({ ...current, autoHideInput }));
  };

  const updateRuntimeDialogOpacity = (dialogOpacity: number) => {
    setRuntimeConfig((current) => ({ ...current, dialogOpacity }));
  };

  const updateRuntimeDialogFill: Parameters<typeof ChatConfigDialog>[0]["onDialogFillChange"] = (patch) => {
    setRuntimeConfig((current) => ({ ...current, dialogFill: { ...current.dialogFill, ...patch } }));
  };

  const updateRuntimeDialogScale = (dialogScale: number) => {
    setRuntimeConfig((current) => ({ ...current, dialogScale }));
  };

  const updateRuntimeSpriteOffsetX = (spriteOffsetX: number) => {
    setRuntimeConfig((current) => ({ ...current, spriteOffsetX }));
  };

  const updateRuntimeSpriteOffsetY = (spriteOffsetY: number) => {
    setRuntimeConfig((current) => ({ ...current, spriteOffsetY }));
  };

  const updateRuntimeSpriteScale = (spriteKey: string, spriteScale: number) => {
    setRuntimeConfig((current) => ({
      ...current,
      spriteScales: {
        ...current.spriteScales,
        [spriteKey]: spriteScale,
      },
    }));
  };

  const updateRuntimeWindowScale = (windowScale: number) => {
    setRuntimeConfig((current) => ({ ...current, windowScale }));
  };

  const updateRuntimeConfigThemeColor = (configThemeColor: string) => {
    setRuntimeConfig((current) => ({ ...current, configThemeColor: normalizeThemeColor(configThemeColor) }));
  };

  const updateRuntimeConfigUseMainThemeColor = (configUseMainThemeColor: boolean) => {
    setRuntimeConfig((current) => ({ ...current, configUseMainThemeColor }));
  };

  const updateRuntimeLongPressTalk = (longPressTalk: boolean) => {
    if (longPressTalk && !voskModelState.available) {
      showToast({
        kind: "info",
        message: t("chat.config.longPressTalkVoskMissing", { path: voskModelState.path || VOSK_MODEL_PATH }),
        title: t("chat.config.longPressTalk"),
      });
      return;
    }
    setRuntimeConfig((current) => ({ ...current, longPressTalk }));
  };

  const updateRuntimeTextStyle: Parameters<typeof ChatConfigDialog>[0]["onTextStyleChange"] = (target, patch) => {
    setRuntimeConfig((current) => ({
      ...current,
      [target]: {
        ...current[target],
        ...patch,
      },
    }));
  };

  const advanceDialog = useCallback(() => {
    if (typingDialog) {
      showFullDialog();
      return;
    }
    if (!viewModel.layers.dialog || !dialogTotalCharacters) {
      return;
    }
    void sendCommand({ type: "dialog-advance" });
  }, [dialogTotalCharacters, sendCommand, showFullDialog, typingDialog, viewModel.layers.dialog]);

  const toggleAuto = useCallback(() => {
    setRuntimeConfig((current) => ({ ...current, auto: !current.auto }));
  }, []);

  useChatStageKeyboardShortcuts({
    disabled: modalOpen,
    onAdvance: advanceDialog,
    onToggleAuto: toggleAuto,
  });

  const openHistoryDialog = () => {
    setHistoryDialogOpen(true);
    void refreshHistory();
  };

  const closeSurface = () => {
    return closeChatSurface({
      closeRuntime: closeChatRuntime,
      navigate,
      snapshot: state,
    });
  };

  const dialogSurfaceVisible = viewModel.layers.dialog || viewModel.layers.options;
  const dialogToolbar = (
    <DialogStageControls
      asrPaused={viewModel.status === "paused"}
      auto={runtimeConfig.auto}
      closeLabel={t(standaloneDesktopWindow ? "desktop.titlebar.close" : "chat.toolbar.close")}
      configOpen={toolbarConfigOpen}
      hidden={!dialogSurfaceVisible}
      hideCloseButton={standaloneDesktopWindow}
      locked={dialogControlsLocked}
      onAutoChange={(auto) => setRuntimeConfig((current) => ({ ...current, auto }))}
      onCloseSurface={closeSurface}
      onCommand={sendCommand}
      onConfigOpenChange={setToolbarConfigOpen}
      onLockedChange={setDialogControlsLocked}
      onOpenBranches={() => setBranchDialogOpen(true)}
      onOpenHistory={openHistoryDialog}
      showBranches={conversationTreeEnabled}
      showAsrControl={!viewModel.layers.input && viewModel.status === "paused"}
    />
  );

  return (
    <>
      <main
        className="chat-stage"
        data-background={transparentBackground ? "transparent" : "media"}
        data-click-through={clickThroughEnabled ? "true" : "false"}
        data-token-visible={tokenUsageVisible ? "true" : "false"}
        onContextMenuCapture={handleStageContextMenu}
        onFocusCapture={handleStageFocus}
        onPointerDownCapture={handleStagePointerDown}
        onPointerLeave={handleStagePointerLeave}
        onPointerMoveCapture={handleStagePointerMove}
        style={stageStyle}
      >
        <StandaloneDesktopResizeHandles hidden={!standaloneDesktopWindow} />
        <TopStageTools
          autoHide={runtimeConfig.immersiveMode && runtimeConfig.autoHideTopTools}
          hidden={!viewModel.layers.toolbar}
          onCloseDesktopWindow={closeSurface}
          onThemePickerOpenChange={setThemePickerOpen}
          onTokenUsageOpenChange={setTokenUsageOpen}
          standaloneDesktopWindow={standaloneDesktopWindow}
          status={viewModel.statusText}
          themePickerOpen={themePickerOpen}
          tokenUsageAvailable={Boolean(viewModel.tokenUsageText)}
          tokenUsageOpen={tokenUsageOpen}
          transportMode={viewModel.transportMode}
          transportState={viewModel.transportState}
        />
        <BackgroundLayer
          hidden={!viewModel.layers.background}
          path={viewModel.backgroundPath}
          transparent={transparentBackground}
        />
        <CgLayer hidden={!viewModel.layers.cg} path={viewModel.cgPath} />
        <SpriteLayer
          hidden={!viewModel.layers.sprites}
          onDragStart={standaloneDesktopWindow ? handleSpriteDragStart : undefined}
          runtimeScaleForSprite={(sprite, index) => runtimeSpriteScale(runtimeConfig, sprite, index)}
          speaker={viewModel.dialogCharacterName}
          sprites={viewModel.sprites}
        />
        <TokenUsageLayer hidden={!tokenUsageVisible} text={viewModel.tokenUsageText} />
        <BusyLayer hidden={!viewModel.layers.busy} text={viewModel.busyText} />
        <NotificationLayer hidden={!viewModel.layers.notification} text={viewModel.notificationText} />
        <div
          aria-hidden={!dialogSurfaceVisible}
          className={layerClassName("dialog-stack", !dialogSurfaceVisible)}
          hidden={!dialogSurfaceVisible}
        >
          {viewModel.layers.options ? (
            <>
              <OptionsLayer hidden={false} onSelect={submitOption} options={viewModel.options} />
              {!dialogToolbarDetached ? <div className="dialog-layer__toolbar">{dialogToolbar}</div> : null}
            </>
          ) : (
            <DialogLayer
              canAdvance={viewModel.layers.dialog && !typingDialog && dialogTotalCharacters > 0}
              characterName={viewModel.dialogCharacterName}
              hidden={!viewModel.layers.dialog}
              htmlNodes={displayedDialog.nodes}
              onAdvance={advanceDialog}
              onSkip={typingDialog ? advanceDialog : undefined}
              text={typingDialog ? displayedDialog.text : viewModel.dialogText}
              textDirection={dialogTextDirection}
              toolbar={dialogToolbarDetached ? undefined : dialogToolbar}
              typing={typingDialog}
            />
          )}
        </div>
        {dialogToolbarDetached ? (
          <div
            aria-hidden={!dialogSurfaceVisible}
            className={layerClassName("dialog-toolbar-layer", !dialogSurfaceVisible)}
            data-chat-stage-hitbox="true"
            data-locked={dialogControlsLocked ? "true" : "false"}
            data-placement={dialogToolbarPlacement}
            data-reveal={dialogToolbarReveal}
            hidden={!dialogSurfaceVisible}
          >
            {dialogToolbar}
          </div>
        ) : null}
        <InputLayer
          asrPaused={viewModel.status === "paused"}
          autoHide={runtimeConfig.immersiveMode && runtimeConfig.autoHideInput}
          disabled={viewModel.inputDisabled}
          hidden={!viewModel.layers.input}
          inputLayout={inputLayout}
          longPressTalkEnabled={longPressTalkEnabled}
          onChange={(text) => dispatch({ text, type: "setDraft" })}
          onCommand={sendCommand}
          onSubmit={submit}
          value={viewModel.inputDraft}
        />
        <HistoryDialog
          entries={state.historyEntries ?? []}
          forkEnabled={forkHistoryEnabled}
          loading={historyLoading}
          onClose={() => setHistoryDialogOpen(false)}
          onFork={(userIndex) => {
            setHistoryDialogOpen(false);
            void sendCommand({ payload: { userIndex }, type: "fork-history" });
          }}
          onRefresh={() => {
            void refreshHistory();
          }}
          onRevert={(userIndex) => setConfirmRevertUserIndex(userIndex)}
          open={historyDialogOpen}
          userDisplayName={viewModel.userDisplayName}
        />
        {conversationTreeEnabled ? (
          <ConversationTreeDialog
            onClose={() => setBranchDialogOpen(false)}
            onRenameBranch={(branchId, label) => {
              void sendCommand({ payload: { branchId, label }, type: "rename-branch" });
            }}
            onSwitchBranch={(branchId) => {
              void sendCommand({ payload: branchId, type: "switch-branch" });
            }}
            open={branchDialogOpen}
            tree={state.conversationTree}
          />
        ) : null}
        <ChatConfigDialog
          autoHideInput={runtimeConfig.autoHideInput}
          autoHideTopTools={runtimeConfig.autoHideTopTools}
          configThemeColor={runtimeConfig.configThemeColor}
          configUseMainThemeColor={runtimeConfig.configUseMainThemeColor}
          dialogFill={runtimeConfig.dialogFill}
          dialogText={runtimeConfig.dialogText}
          dialogOpacity={runtimeConfig.dialogOpacity}
          dialogScale={runtimeConfig.dialogScale}
          effectiveDialogText={effectiveDialogText}
          effectiveNameText={effectiveNameText}
          immersiveMode={runtimeConfig.immersiveMode}
          longPressTalk={runtimeConfig.longPressTalk}
          longPressTalkAvailable={voskModelState.available}
          longPressTalkVisible={longPressTalkVisible}
          mainThemeColor={mainThemeColor}
          nameText={runtimeConfig.nameText}
          onClose={() => setToolbarConfigOpen(false)}
          onCommand={sendCommand}
          onAutoHideInputChange={updateRuntimeAutoHideInput}
          onAutoHideTopToolsChange={updateRuntimeAutoHideTopTools}
          onConfigThemeColorChange={updateRuntimeConfigThemeColor}
          onConfigUseMainThemeColorChange={updateRuntimeConfigUseMainThemeColor}
          onDialogFillChange={updateRuntimeDialogFill}
          onDialogOpacityChange={updateRuntimeDialogOpacity}
          onDialogScaleChange={updateRuntimeDialogScale}
          onImmersiveModeChange={updateRuntimeImmersiveMode}
          onLongPressTalkChange={updateRuntimeLongPressTalk}
          onSpriteOffsetXChange={updateRuntimeSpriteOffsetX}
          onSpriteOffsetYChange={updateRuntimeSpriteOffsetY}
          onSpriteScaleChange={updateRuntimeSpriteScale}
          onTextSpeedChange={updateRuntimeTextSpeed}
          onTextStyleChange={updateRuntimeTextStyle}
          onWindowScaleChange={updateRuntimeWindowScale}
          open={toolbarConfigOpen}
          spriteOffsetX={runtimeConfig.spriteOffsetX}
          spriteOffsetY={runtimeConfig.spriteOffsetY}
          spriteScales={runtimeConfig.spriteScales}
          sprites={viewModel.sprites}
          textSpeed={typewriterCps}
          voiceLanguage={viewModel.voiceLanguage || "ja"}
          windowScale={runtimeConfig.windowScale}
        />
      </main>
      <AlertDialog
        body={t("chat.clear.confirmBody")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("chat.clear.confirmAction")}
        onCancel={() => setConfirmClearHistory(false)}
        onConfirm={() => void sendCommand({ type: "clear-history" })}
        open={confirmClearHistory}
        title={t("chat.clear.confirmTitle")}
      />
      <AlertDialog
        body={t("chat.history.revertConfirmBody")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("chat.history.revertConfirmAction")}
        onCancel={() => setConfirmRevertUserIndex(null)}
        onConfirm={() => {
          if (confirmRevertUserIndex == null) {
            return;
          }
          setConfirmRevertUserIndex(null);
          setHistoryDialogOpen(false);
          void sendCommand({ payload: confirmRevertUserIndex, type: "revert-history" });
        }}
        open={confirmRevertUserIndex != null}
        title={t("chat.history.revertConfirmTitle")}
      />
    </>
  );
}
