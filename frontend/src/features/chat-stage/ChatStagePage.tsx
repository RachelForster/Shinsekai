import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type FocusEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  closeChat,
  getChatHistory,
  getChatSnapshot,
  sendChatCommand,
  subscribeChatEvents,
} from "../../entities/chat/repository";
import {
  getDesktopWindowCursorPosition,
  isTauriDesktop,
  setDesktopWindowClickThrough,
} from "../../shared/desktop/desktopApi";
import { closeChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import type { ChatCommand, ChatSnapshot } from "../../shared/platform/types";
import { DEFAULT_TYPEWRITER_CPS } from "../../shared/theme/chatTheme";
import { AlertDialog, useToast } from "../../shared/ui";
import { ChatConfigDialog } from "./components/ChatConfigDialog";
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
import { isChatStageHitbox, isPointInsideChatStageHitbox, layerClassName } from "./chatStageUtils";
import { buildDialogTypewriterSource, renderDialogTypewriterFrame } from "./dialogTypewriter";
import {
  chatStageRuntimeStyle,
  clickThroughGuardIntervalMs,
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
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [dialogControlsLocked, setDialogControlsLocked] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState(readChatStageRuntimeConfig);
  const [tokenUsageOpen, setTokenUsageOpen] = useState(false);
  const [toolbarConfigOpen, setToolbarConfigOpen] = useState(false);
  const [visibleDialogCharacters, setVisibleDialogCharacters] = useState(0);
  const { showToast } = useToast();
  const { t } = useI18n();
  const theme = useOptionalChatTheme();
  const themeStyle = theme?.style ?? {};
  const stageStyle = useMemo(() => chatStageRuntimeStyle(runtimeConfig, themeStyle), [runtimeConfig, themeStyle]);
  const viewModel = useMemo(() => buildChatStageViewModel(state), [state]);
  const standaloneDesktopWindow = isTauriDesktop() && location.pathname === "/chat-stage";
  const transparentBackground = !viewModel.backgroundPath;
  const tokenUsageVisible = tokenUsageOpen && Boolean(viewModel.tokenUsageText);
  const modalOpen = toolbarConfigOpen || historyDialogOpen || confirmClearHistory || confirmRevertUserIndex != null;
  const clickThroughEnabled = standaloneDesktopWindow && transparentBackground && !modalOpen;
  const eventSeqRef = useRef(0);
  eventSeqRef.current = state.eventSeq;
  const pendingAnimatedDialogKeyRef = useRef<string | null>(null);
  const clickThroughIgnoredRef = useRef(false);
  const clickThroughGuardIntervalRef = useRef<number | null>(null);
  const clickThroughGuardPollingRef = useRef(false);
  const dialogSource = useMemo(
    () =>
      buildDialogTypewriterSource({
        characterName: viewModel.dialogCharacterName,
        html: viewModel.dialogHtml,
        text: viewModel.dialogText,
      }),
    [viewModel.dialogCharacterName, viewModel.dialogHtml, viewModel.dialogText],
  );
  const typewriterCps = runtimeConfig.typewriterCps ?? theme?.resolved?.typewriter.cps ?? DEFAULT_TYPEWRITER_CPS;
  const displayedDialog = useMemo(
    () => renderDialogTypewriterFrame(dialogSource, visibleDialogCharacters),
    [dialogSource, visibleDialogCharacters],
  );
  const typingDialog = visibleDialogCharacters < dialogSource.totalCharacters;

  const stopClickThroughGuard = useCallback(() => {
    if (clickThroughGuardIntervalRef.current == null) {
      return;
    }
    window.clearInterval(clickThroughGuardIntervalRef.current);
    clickThroughGuardIntervalRef.current = null;
  }, []);

  const applyClickThroughIgnored = useCallback((ignore: boolean) => {
    if (clickThroughIgnoredRef.current === ignore) {
      return;
    }
    clickThroughIgnoredRef.current = ignore;
    void setDesktopWindowClickThrough(ignore).catch((error) => {
      console.error("Desktop chat window click-through update failed", error);
    });
  }, []);

  const disableClickThrough = useCallback(() => {
    stopClickThroughGuard();
    applyClickThroughIgnored(false);
  }, [applyClickThroughIgnored, stopClickThroughGuard]);

  const startClickThroughGuard = useCallback(() => {
    if (clickThroughGuardIntervalRef.current != null) {
      return;
    }
    const pollCursor = async () => {
      if (clickThroughGuardPollingRef.current) {
        return;
      }
      clickThroughGuardPollingRef.current = true;
      try {
        const cursor = await getDesktopWindowCursorPosition();
        if (isPointInsideChatStageHitbox(cursor.x, cursor.y)) {
          disableClickThrough();
        }
      } catch (error) {
        console.error("Desktop chat window cursor guard failed", error);
        disableClickThrough();
      } finally {
        clickThroughGuardPollingRef.current = false;
      }
    };
    clickThroughGuardIntervalRef.current = window.setInterval(pollCursor, clickThroughGuardIntervalMs);
    void pollCursor();
  }, [disableClickThrough]);

  const enableClickThrough = useCallback(() => {
    applyClickThroughIgnored(true);
    startClickThroughGuard();
  }, [applyClickThroughIgnored, startClickThroughGuard]);

  const setClickThroughIgnored = useCallback(
    (ignore: boolean) => {
      if (ignore) {
        enableClickThrough();
      } else {
        disableClickThrough();
      }
    },
    [disableClickThrough, enableClickThrough],
  );

  useEffect(() => {
    if (transparentBackground) {
      document.documentElement.dataset.chatStageTransparent = "true";
      document.body.dataset.chatStageTransparent = "true";
    } else {
      delete document.documentElement.dataset.chatStageTransparent;
      delete document.body.dataset.chatStageTransparent;
    }
    return () => {
      delete document.documentElement.dataset.chatStageTransparent;
      delete document.body.dataset.chatStageTransparent;
    };
  }, [transparentBackground]);

  useEffect(() => {
    if (!standaloneDesktopWindow) {
      return;
    }
    if (!clickThroughEnabled) {
      setClickThroughIgnored(false);
    }
    return () => {
      setClickThroughIgnored(false);
    };
  }, [clickThroughEnabled, setClickThroughIgnored, standaloneDesktopWindow]);

  useEffect(
    () => () => {
      stopClickThroughGuard();
    },
    [stopClickThroughGuard],
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

  useEffect(() => {
    writeChatStageRuntimeConfig(runtimeConfig);
  }, [runtimeConfig]);

  useEffect(() => {
    let mounted = true;
    getChatSnapshot()
      .then((snapshot: ChatSnapshot) => {
        if (mounted) {
          dispatch({ snapshot, type: "hydrate" });
        }
      })
      .catch((error) => {
        dispatch({ message: error instanceof Error ? error.message : t("chat.error.loadFallback"), type: "error" });
      });
    const unsubscribe = subscribeChatEvents((event) => {
      if (event.type === "dialog.end" && event.seq > eventSeqRef.current) {
        if (!event.isSystem || event.speaker.trim()) {
          pendingAnimatedDialogKeyRef.current = buildDialogTypewriterSource({
            characterName: event.speaker,
            html: event.fullHtml,
          }).cacheKey;
          setVisibleDialogCharacters(0);
        }
      }
      dispatch({ event, type: "event" });
    });
    return () => {
      mounted = false;
      unsubscribe();
    };
  }, [t]);

  useEffect(() => {
    const pendingKey = pendingAnimatedDialogKeyRef.current;
    if (pendingKey === dialogSource.cacheKey) {
      pendingAnimatedDialogKeyRef.current = null;
      return;
    }
    setVisibleDialogCharacters(dialogSource.totalCharacters);
  }, [dialogSource.cacheKey, dialogSource.totalCharacters]);

  useEffect(() => {
    if (visibleDialogCharacters >= dialogSource.totalCharacters) {
      return;
    }
    const delayMs = Math.max(16, Math.round(1000 / Math.max(1, typewriterCps)));
    const timeoutId = window.setTimeout(() => {
      setVisibleDialogCharacters((current) => Math.min(dialogSource.totalCharacters, current + 1));
    }, delayMs);
    return () => window.clearTimeout(timeoutId);
  }, [dialogSource.totalCharacters, typewriterCps, visibleDialogCharacters]);

  const refreshHistory = async () => {
    setHistoryLoading(true);
    try {
      const historyEntries = await getChatHistory();
      dispatch({ historyEntries, type: "setHistoryEntries" });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.error.commandFallback"),
        title: t("common.operationFailed"),
      });
    } finally {
      setHistoryLoading(false);
    }
  };

  const sendCommand = async (command: ChatCommand) => {
    if (command.type === "clear-history" && !confirmClearHistory) {
      setConfirmClearHistory(true);
      return;
    }
    try {
      const snapshot = await sendChatCommand(command);
      dispatch({ snapshot, type: "hydrate" });
      if (command.type === "copy-history") {
        showToast({ kind: "success", title: t("chat.toast.historyCopied") });
      }
      if (command.type === "open-history") {
        showToast({
          kind: "success",
          message: snapshot.openedPath || snapshot.historyPath,
          title: t("chat.toast.historyOpened"),
        });
      }
      if (command.type === "clear-history") {
        setConfirmClearHistory(false);
        showToast({ kind: "success", title: t("chat.toast.historyCleared") });
      }
    } catch (error) {
      dispatch({ status: "idle", type: "setStatus" });
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.error.commandFallback"),
        title: t("common.operationFailed"),
      });
    }
  };

  const submit = () => {
    const text = viewModel.inputDraft.trim();
    if (!text) {
      return;
    }
    dispatch({ status: "generating", type: "setStatus" });
    void sendCommand({ payload: text, type: "send-message" });
  };

  const updateRuntimeTextSpeed = (typewriterCps: number) => {
    setRuntimeConfig((current) => ({ ...current, typewriterCps }));
  };

  const updateRuntimeDialogOpacity = (dialogOpacity: number) => {
    setRuntimeConfig((current) => ({ ...current, dialogOpacity }));
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

  const advanceDialog = () => {
    if (typingDialog) {
      setVisibleDialogCharacters(dialogSource.totalCharacters);
      return;
    }
    if (!viewModel.layers.dialog || !dialogSource.totalCharacters) {
      return;
    }
    void sendCommand({ type: "dialog-advance" });
  };

  const openHistoryDialog = () => {
    setHistoryDialogOpen(true);
    void refreshHistory();
  };

  const closeSurface = () => {
    void closeChatSurface({
      closeRuntime: closeChat,
      navigate,
      snapshot: state,
    });
  };

  const handleStagePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (!clickThroughEnabled) {
        return;
      }
      if (isChatStageHitbox(event.target)) {
        setClickThroughIgnored(false);
        return;
      }
      setClickThroughIgnored(true);
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStagePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (!clickThroughEnabled || isChatStageHitbox(event.target)) {
        return;
      }
      setClickThroughIgnored(true);
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStagePointerLeave = useCallback(() => {
    if (standaloneDesktopWindow) {
      setClickThroughIgnored(false);
    }
  }, [setClickThroughIgnored, standaloneDesktopWindow]);

  const handleStageFocus = useCallback(
    (event: FocusEvent<HTMLElement>) => {
      if (clickThroughEnabled && isChatStageHitbox(event.target)) {
        setClickThroughIgnored(false);
      }
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  return (
    <>
      <main
        className="chat-stage"
        data-background={transparentBackground ? "transparent" : "media"}
        data-click-through={clickThroughEnabled ? "true" : "false"}
        data-token-visible={tokenUsageVisible ? "true" : "false"}
        onFocusCapture={handleStageFocus}
        onPointerDownCapture={handleStagePointerDown}
        onPointerLeave={handleStagePointerLeave}
        onPointerMoveCapture={handleStagePointerMove}
        style={stageStyle}
      >
        <StandaloneDesktopResizeHandles hidden={!standaloneDesktopWindow} />
        <TopStageTools
          hidden={!viewModel.layers.toolbar}
          onTokenUsageOpenChange={setTokenUsageOpen}
          standaloneDesktopWindow={standaloneDesktopWindow}
          status={viewModel.statusText}
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
          runtimeScaleForSprite={(sprite, index) => runtimeSpriteScale(runtimeConfig, sprite, index)}
          sprites={viewModel.sprites}
        />
        <TokenUsageLayer hidden={!tokenUsageVisible} text={viewModel.tokenUsageText} />
        <BusyLayer hidden={!viewModel.layers.busy} text={viewModel.busyText} />
        <NotificationLayer hidden={!viewModel.layers.notification} text={viewModel.notificationText} />
        <div
          aria-hidden={!viewModel.layers.dialog}
          className={layerClassName("dialog-stack", !viewModel.layers.dialog)}
          hidden={!viewModel.layers.dialog}
        >
          <DialogStageControls
            asrPaused={viewModel.status === "paused"}
            closeLabel={t(standaloneDesktopWindow ? "desktop.titlebar.close" : "chat.toolbar.close")}
            configOpen={toolbarConfigOpen}
            hidden={!viewModel.layers.dialog}
            hideCloseButton={standaloneDesktopWindow}
            locked={dialogControlsLocked}
            onCloseSurface={closeSurface}
            onCommand={sendCommand}
            onConfigOpenChange={setToolbarConfigOpen}
            onLockedChange={setDialogControlsLocked}
            onOpenHistory={openHistoryDialog}
            showAsrControl={!viewModel.layers.input && viewModel.status === "paused"}
          />
          <DialogLayer
            canAdvance={viewModel.layers.dialog && !typingDialog && dialogSource.totalCharacters > 0}
            characterName={viewModel.dialogCharacterName}
            hidden={!viewModel.layers.dialog}
            html={displayedDialog.html}
            onAdvance={advanceDialog}
            onSkip={typingDialog ? advanceDialog : undefined}
            text={typingDialog ? displayedDialog.text : viewModel.dialogText}
            typing={typingDialog}
          />
        </div>
        <OptionsLayer
          hidden={!viewModel.layers.options}
          onSelect={(option) => void sendCommand({ payload: option, type: "submit-option" })}
          options={viewModel.options}
        />
        <InputLayer
          asrPaused={viewModel.status === "paused"}
          disabled={viewModel.inputDisabled}
          hidden={!viewModel.layers.input}
          onChange={(text) => dispatch({ text, type: "setDraft" })}
          onCommand={sendCommand}
          onSubmit={submit}
          value={viewModel.inputDraft}
        />
        <HistoryDialog
          entries={state.historyEntries ?? []}
          loading={historyLoading}
          onClose={() => setHistoryDialogOpen(false)}
          onRefresh={() => {
            void refreshHistory();
          }}
          onRevert={(userIndex) => setConfirmRevertUserIndex(userIndex)}
          open={historyDialogOpen}
          userDisplayName={viewModel.userDisplayName}
        />
        <ChatConfigDialog
          dialogOpacity={runtimeConfig.dialogOpacity}
          dialogScale={runtimeConfig.dialogScale}
          onClose={() => setToolbarConfigOpen(false)}
          onCommand={sendCommand}
          onDialogOpacityChange={updateRuntimeDialogOpacity}
          onDialogScaleChange={updateRuntimeDialogScale}
          onSpriteOffsetXChange={updateRuntimeSpriteOffsetX}
          onSpriteOffsetYChange={updateRuntimeSpriteOffsetY}
          onSpriteScaleChange={updateRuntimeSpriteScale}
          onTextSpeedChange={updateRuntimeTextSpeed}
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
