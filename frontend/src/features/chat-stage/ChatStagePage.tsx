import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type FocusEvent,
  type MouseEvent as ReactMouseEvent,
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
import { getAppConfig } from "../../entities/config/repository";
import { browseFiles } from "../../entities/files/repository";
import {
  getDesktopWindowCursorPosition,
  isTauriDesktop,
  setDesktopWindowClickThrough,
} from "../../shared/desktop/desktopApi";
import { closeChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import type { ChatCommand, ChatSnapshot, FileBrowserSnapshot } from "../../shared/platform/types";
import { normalizeThemeColor } from "../../shared/theme/appTheme";
import { DEFAULT_TYPEWRITER_CPS } from "../../shared/theme/chatTheme";
import { AlertDialog, useToast } from "../../shared/ui";
import { VOSK_MODEL_PATH } from "../api-settings/apiSettingsUtils";
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
import { isChatStageHitbox, isPointInsideChatStageHitbox, layerClassName } from "./chatStageUtils";
import { buildDialogTypewriterSource, renderDialogTypewriterFrame } from "./dialogTypewriter";
import {
  chatStageRuntimeStyle,
  clickThroughGuardIntervalMs,
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
  readChatStageRuntimeConfig,
  runtimeSpriteScale,
  writeChatStageRuntimeConfig,
} from "./runtimeConfig";
import { useOptionalChatTheme } from "./theme/ChatThemeProvider";

const AUTO_ADVANCE_DELAY_MS = 1600;

function readMainThemeColor() {
  if (typeof window === "undefined") {
    return normalizeThemeColor(undefined);
  }
  return normalizeThemeColor(getComputedStyle(document.documentElement).getPropertyValue("--theme-accent"));
}

function isStartOptionLabel(option: string) {
  const normalized = option.trim().toLocaleLowerCase();
  return normalized === "start" || normalized === "开始" || normalized === "開始" || normalized === "スタート";
}

function snapshotLooksLikeVoskModel(snapshot: FileBrowserSnapshot) {
  const names = new Set(snapshot.entries.map((entry) => entry.name.toLocaleLowerCase()));
  return names.has("am") && names.has("conf") && names.has("graph");
}

export function ChatStagePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(chatStageReducer, emptyChatState);
  const [confirmClearHistory, setConfirmClearHistory] = useState(false);
  const [confirmRevertUserIndex, setConfirmRevertUserIndex] = useState<number | null>(null);
  const [branchDialogOpen, setBranchDialogOpen] = useState(false);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [dialogControlsLocked, setDialogControlsLocked] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState(readChatStageRuntimeConfig);
  const [mainThemeColor, setMainThemeColor] = useState(readMainThemeColor);
  const [tokenUsageOpen, setTokenUsageOpen] = useState(false);
  const [toolbarConfigOpen, setToolbarConfigOpen] = useState(false);
  const [visibleDialogCharacters, setVisibleDialogCharacters] = useState(0);
  const [voskModelState, setVoskModelState] = useState({
    available: false,
    loading: true,
    path: VOSK_MODEL_PATH,
  });
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
  const transparentBackground = !viewModel.backgroundPath;
  const tokenUsageVisible = tokenUsageOpen && Boolean(viewModel.tokenUsageText);
  const modalOpen =
    toolbarConfigOpen || branchDialogOpen || historyDialogOpen || confirmClearHistory || confirmRevertUserIndex != null;
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
  const hideNameWhenStartOption = themeStyle["--chat-name-hide-when-start-option"] === "true";
  const nameHiddenForStartOption =
    hideNameWhenStartOption && viewModel.layers.options && viewModel.options.some(isStartOptionLabel);
  const eventSeqRef = useRef(0);
  eventSeqRef.current = state.eventSeq;
  const pendingAnimatedDialogKeyRef = useRef<string | null>(null);
  const advanceDialogRef = useRef<() => void>(() => {});
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
  const dialogTextDirection = effectiveDialogText.direction ?? "ltr";
  const dialogTotalCharacters =
    dialogTextDirection === "rtl" ? dialogSource.totalRtlCharacters : dialogSource.totalCharacters;
  const typewriterCps = runtimeConfig.typewriterCps ?? theme?.resolved?.typewriter.cps ?? DEFAULT_TYPEWRITER_CPS;
  const displayedDialog = useMemo(
    () => renderDialogTypewriterFrame(dialogSource, visibleDialogCharacters, dialogTextDirection),
    [dialogSource, dialogTextDirection, visibleDialogCharacters],
  );
  const typingDialog = visibleDialogCharacters < dialogTotalCharacters;

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

  useEffect(() => {
    const syncMainThemeColor = () => setMainThemeColor(readMainThemeColor());
    setMainThemeColor(readMainThemeColor());
    const observer = typeof MutationObserver === "undefined" ? null : new MutationObserver(syncMainThemeColor);
    observer?.observe(document.documentElement, { attributeFilter: ["class", "style"], attributes: true });
    window.addEventListener("storage", syncMainThemeColor);
    return () => {
      observer?.disconnect();
      window.removeEventListener("storage", syncMainThemeColor);
    };
  }, []);

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
    let cancelled = false;
    const probeVoskModel = async () => {
      let modelPath = VOSK_MODEL_PATH;
      try {
        const appConfig = await getAppConfig();
        const configuredPath = String(appConfig.api_config.asr_extra_configs?.vosk?.model_path ?? "").trim();
        modelPath = configuredPath || VOSK_MODEL_PATH;
        const snapshot = await browseFiles({ path: modelPath, showHidden: false });
        if (!cancelled) {
          setVoskModelState({ available: snapshotLooksLikeVoskModel(snapshot), loading: false, path: modelPath });
        }
      } catch {
        if (!cancelled) {
          setVoskModelState({ available: false, loading: false, path: modelPath });
        }
      }
    };
    void probeVoskModel();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!voskModelState.loading && !voskModelState.available && runtimeConfig.longPressTalk) {
      setRuntimeConfig((current) => (current.longPressTalk ? { ...current, longPressTalk: false } : current));
    }
  }, [runtimeConfig.longPressTalk, voskModelState.available, voskModelState.loading]);

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
    setVisibleDialogCharacters(dialogTotalCharacters);
  }, [dialogSource.cacheKey, dialogTotalCharacters]);

  useEffect(() => {
    if (visibleDialogCharacters >= dialogTotalCharacters) {
      return;
    }
    const delayMs = Math.max(16, Math.round(1000 / Math.max(1, typewriterCps)));
    const timeoutId = window.setTimeout(() => {
      setVisibleDialogCharacters((current) => Math.min(dialogTotalCharacters, current + 1));
    }, delayMs);
    return () => window.clearTimeout(timeoutId);
  }, [dialogTotalCharacters, typewriterCps, visibleDialogCharacters]);

  // AUTO mode: once a line finishes typing, wait then advance — pauses at choices / while generating.
  useEffect(() => {
    if (!runtimeConfig.auto || typingDialog) {
      return;
    }
    if (!viewModel.layers.dialog || viewModel.layers.options || !dialogTotalCharacters) {
      return;
    }
    if (viewModel.status === "generating" || viewModel.status === "streaming") {
      return;
    }
    const timeoutId = window.setTimeout(() => advanceDialogRef.current(), AUTO_ADVANCE_DELAY_MS);
    return () => window.clearTimeout(timeoutId);
  }, [
    dialogSource.cacheKey,
    dialogTotalCharacters,
    runtimeConfig.auto,
    typingDialog,
    viewModel.layers.dialog,
    viewModel.layers.options,
    viewModel.status,
  ]);

  // Keyboard: Space/Enter advances (or skips typing), A toggles AUTO — ignored while typing in a field.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (modalOpen) {
        return;
      }
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        advanceDialogRef.current();
      } else if (event.key === "a" || event.key === "A") {
        setRuntimeConfig((current) => ({ ...current, auto: !current.auto }));
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [modalOpen]);

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
      if (command.type !== "copy-history") {
        dispatch({ snapshot, type: "hydrate" });
      }
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

  const advanceDialog = () => {
    if (typingDialog) {
      setVisibleDialogCharacters(dialogTotalCharacters);
      return;
    }
    if (!viewModel.layers.dialog || !dialogTotalCharacters) {
      return;
    }
    void sendCommand({ type: "dialog-advance" });
  };
  advanceDialogRef.current = advanceDialog;

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

  const handleStageContextMenu = useCallback((event: ReactMouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
  }, []);

  const dialogToolbar = (
    <DialogStageControls
      asrPaused={viewModel.status === "paused"}
      auto={runtimeConfig.auto}
      closeLabel={t(standaloneDesktopWindow ? "desktop.titlebar.close" : "chat.toolbar.close")}
      configOpen={toolbarConfigOpen}
      hidden={!viewModel.layers.dialog}
      hideCloseButton={standaloneDesktopWindow}
      locked={dialogControlsLocked}
      onAutoChange={(auto) => setRuntimeConfig((current) => ({ ...current, auto }))}
      onCloseSurface={closeSurface}
      onCommand={sendCommand}
      onConfigOpenChange={setToolbarConfigOpen}
      onLockedChange={setDialogControlsLocked}
      onOpenBranches={() => setBranchDialogOpen(true)}
      onOpenHistory={openHistoryDialog}
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
          speaker={viewModel.dialogCharacterName}
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
          <DialogLayer
            canAdvance={viewModel.layers.dialog && !typingDialog && dialogTotalCharacters > 0}
            characterName={nameHiddenForStartOption ? undefined : viewModel.dialogCharacterName}
            hidden={!viewModel.layers.dialog}
            html={displayedDialog.html}
            onAdvance={advanceDialog}
            onSkip={typingDialog ? advanceDialog : undefined}
            text={typingDialog ? displayedDialog.text : viewModel.dialogText}
            textDirection={dialogTextDirection}
            toolbar={dialogToolbarDetached ? undefined : dialogToolbar}
            typing={typingDialog}
          />
        </div>
        {dialogToolbarDetached ? (
          <div
            aria-hidden={!viewModel.layers.dialog}
            className={layerClassName("dialog-toolbar-layer", !viewModel.layers.dialog)}
            data-chat-stage-hitbox="true"
            data-locked={dialogControlsLocked ? "true" : "false"}
            data-placement={dialogToolbarPlacement}
            data-reveal={dialogToolbarReveal}
            hidden={!viewModel.layers.dialog}
          >
            {dialogToolbar}
          </div>
        ) : null}
        <OptionsLayer
          hidden={!viewModel.layers.options}
          onSelect={(option) => void sendCommand({ payload: option, type: "submit-option" })}
          options={viewModel.options}
        />
        <InputLayer
          asrPaused={viewModel.status === "paused"}
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
        <ChatConfigDialog
          configThemeColor={runtimeConfig.configThemeColor}
          configUseMainThemeColor={runtimeConfig.configUseMainThemeColor}
          dialogFill={runtimeConfig.dialogFill}
          dialogText={runtimeConfig.dialogText}
          dialogOpacity={runtimeConfig.dialogOpacity}
          dialogScale={runtimeConfig.dialogScale}
          effectiveDialogText={effectiveDialogText}
          effectiveNameText={effectiveNameText}
          longPressTalk={runtimeConfig.longPressTalk}
          longPressTalkAvailable={voskModelState.available}
          longPressTalkVisible={longPressTalkVisible}
          mainThemeColor={mainThemeColor}
          nameText={runtimeConfig.nameText}
          onClose={() => setToolbarConfigOpen(false)}
          onCommand={sendCommand}
          onConfigThemeColorChange={updateRuntimeConfigThemeColor}
          onConfigUseMainThemeColorChange={updateRuntimeConfigUseMainThemeColor}
          onDialogFillChange={updateRuntimeDialogFill}
          onDialogOpacityChange={updateRuntimeDialogOpacity}
          onDialogScaleChange={updateRuntimeDialogScale}
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
