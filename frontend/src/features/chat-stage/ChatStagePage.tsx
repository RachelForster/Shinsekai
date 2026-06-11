import { useEffect, useMemo, useReducer, useRef, useState, type CSSProperties, type FocusEvent, type KeyboardEvent, type MouseEvent, type SyntheticEvent } from "react";
import { Copy, GripHorizontal, History, Languages, Maximize2, Mic, MicOff, Minus, MoreHorizontal, RotateCcw, Send, SkipForward, Trash2, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { closeChat, getChatHistory, getChatSnapshot, sendChatCommand, subscribeChatEvents } from "../../entities/chat/repository";
import { closeDesktopWindow, isTauriDesktop, minimizeDesktopWindow, startDesktopWindowDrag, toggleMaximizeDesktopWindow } from "../../shared/desktop/desktopApi";
import { closeChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import type { MessageKey } from "../../shared/i18n";
import { PluginSlot } from "../../shared/plugin/PluginSlot";
import type { ChatCommand, ChatHistoryEntry, ChatSnapshot, ChatTransportMode, ChatTransportState } from "../../shared/platform/types";
import { DEFAULT_TYPEWRITER_CPS } from "../../shared/theme/chatTheme";
import { AlertDialog, Button, Dialog, IconButton, Select, TextArea, ToolbarButton, useToast } from "../../shared/ui";
import "./chat-stage.css";
import { buildChatStageViewModel, chatStageReducer, emptyChatState } from "./chatState";
import type { ChatStageSprite } from "./chatState";
import {
  buildDialogTypewriterSource,
  renderDialogTypewriterFrame,
} from "./dialogTypewriter";
import { useOptionalChatTheme } from "./theme/ChatThemeProvider";
import { ChatThemePicker } from "./theme/ChatThemePicker";

const chatVoiceLanguages = [
  { labelKey: "system.asr.langJa", value: "ja" },
  { labelKey: "system.asr.langEn", value: "en" },
  { labelKey: "system.asr.langZh", value: "zh" },
  { labelKey: "system.asr.langYue", value: "yue" },
] as const;

interface BrowserSpeechRecognition {
  abort: () => void;
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: { error?: string; message?: string }) => void) | null;
  onresult:
    | ((event: { resultIndex: number; results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void)
    | null;
  start: () => void;
  stop: () => void;
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

function getSpeechRecognitionConstructor(): BrowserSpeechRecognitionConstructor | null {
  const scope = window as typeof window & {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

function speechRecognitionLanguage(language: string) {
  if (language === "en") {
    return "en-US";
  }
  if (language === "ja") {
    return "ja-JP";
  }
  return "zh-CN";
}

function cleanTranscript(text: string, language: string) {
  const trimmed = text.trim();
  if (language === "en") {
    return trimmed;
  }
  return trimmed.replace(/\s+/g, "");
}

function appendTranscript(base: string, transcript: string, language: string) {
  const text = cleanTranscript(transcript, language);
  if (!text) {
    return base;
  }
  const current = base.trim();
  if (!current) {
    return text;
  }
  const separator = language === "en" ? " " : "，";
  if (/[，。！？,.!?;；:：\s]$/.test(current)) {
    return `${current}${text}`;
  }
  return `${current}${separator}${text}`;
}

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function layerClassName(base: string, hidden: boolean) {
  return classNames(base, hidden && "chat-stage__layer--hidden");
}

function hideBrokenStageAsset(event: SyntheticEvent<HTMLImageElement>) {
  event.currentTarget.dataset.loadState = "error";
}

function transportStatusText(
  t: (key: MessageKey) => string,
  state: ChatTransportState,
  mode: ChatTransportMode,
) {
  if (state === "connected") {
    return mode === "websocket" ? t("chat.transport.connected") : t("chat.transport.snapshot");
  }
  if (state === "polling") {
    return t("chat.transport.polling");
  }
  if (state === "reconnecting") {
    return t("chat.transport.reconnecting");
  }
  return t("chat.transport.connecting");
}

function BackgroundLayer({ hidden, path, transparent }: { hidden: boolean; path?: string; transparent: boolean }) {
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("chat-stage__background", hidden)}
      data-transparent={transparent ? "true" : "false"}
      hidden={hidden}
    >
      {transparent ? null : <div aria-hidden className="chat-stage__fallback" />}
      {path ? <img alt="" onError={hideBrokenStageAsset} src={path} /> : null}
    </div>
  );
}

function CgLayer({ hidden, path }: { hidden: boolean; path?: string }) {
  return (
    <div aria-hidden={hidden} className={layerClassName("chat-stage__cg", hidden)} hidden={hidden}>
      {path ? <img alt="" onError={hideBrokenStageAsset} src={path} /> : null}
    </div>
  );
}

function SpriteLayer({ hidden, sprites }: { hidden: boolean; sprites: ChatStageSprite[] }) {
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("sprite-layer", hidden)}
      data-count={sprites.length}
      hidden={hidden}
    >
      {sprites.map((sprite, index) => (
        <figure
          className="sprite-layer__figure"
          data-slot={sprite.slot ?? index}
          key={sprite.id}
          style={
            {
              "--sprite-count": sprites.length,
              "--sprite-index": index,
              "--sprite-scale": sprite.scale ?? 1,
            } as CSSProperties
          }
        >
          <img
            alt={sprite.label}
            className="sprite-layer__image"
            onError={hideBrokenStageAsset}
            src={sprite.path}
          />
        </figure>
      ))}
    </div>
  );
}

function DialogLayer({
  canAdvance,
  characterName,
  hidden,
  html,
  onAdvance,
  onSkip,
  text,
  typing,
}: {
  canAdvance: boolean;
  characterName?: string;
  hidden: boolean;
  html?: string;
  onAdvance?: () => void;
  onSkip?: () => void;
  text: string;
  typing: boolean;
}) {
  const { t } = useI18n();
  return (
    <section
      aria-hidden={hidden}
      aria-live="polite"
      className={layerClassName("dialog-layer", hidden)}
      data-typing={typing ? "true" : "false"}
      hidden={hidden}
      onClick={typing ? onSkip : canAdvance ? onAdvance : undefined}
    >
      {characterName ? <p className="dialog-layer__name">{characterName}</p> : null}
      {html !== undefined ? (
        <p className="dialog-layer__text" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <p className="dialog-layer__text">{text || t("chat.emptyDialog")}</p>
      )}
      <PluginSlot slot="chat-output" />
    </section>
  );
}

function OptionsLayer({
  hidden,
  onSelect,
  options,
}: {
  hidden: boolean;
  onSelect: (option: string) => void;
  options: string[];
}) {
  if (hidden || !options.length) {
    return null;
  }
  return (
    <div aria-hidden={hidden} className={layerClassName("options-layer", hidden)} hidden={hidden}>
      {options.map((option) => (
        <Button className="options-layer__button" key={option} onClick={() => onSelect(option)}>
          {option}
        </Button>
      ))}
    </div>
  );
}

function BusyLayer({ hidden, text }: { hidden: boolean; text?: string }) {
  if (hidden || !text) {
    return null;
  }
  return (
    <div aria-hidden={hidden} className={layerClassName("chat-stage__busy", hidden)} hidden={hidden} role="status">
      {text}
    </div>
  );
}

function NotificationLayer({ hidden, text }: { hidden: boolean; text?: string }) {
  if (hidden || !text) {
    return null;
  }
  return (
    <div aria-hidden={hidden} className={layerClassName("chat-stage__notification", hidden)} hidden={hidden}>
      {text}
    </div>
  );
}

function StandaloneDesktopWindowControls({ hidden }: { hidden: boolean }) {
  const { t } = useI18n();

  if (hidden) {
    return null;
  }

  const runWindowAction = (action: () => Promise<void>) => {
    void action().catch((error) => {
      console.error("Desktop chat window action failed", error);
    });
  };

  const handleDragStart = (event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0) {
      return;
    }
    void startDesktopWindowDrag().catch((error) => {
      console.error("Desktop chat window drag failed", error);
    });
  };

  return (
    <div className="desktop-chat-controls">
      <div className="desktop-chat-controls__drag" data-tauri-drag-region onMouseDown={handleDragStart}>
        <GripHorizontal aria-hidden className="desktop-chat-controls__drag-icon" />
      </div>
      <div className="desktop-chat-controls__buttons">
        <IconButton label={t("desktop.titlebar.minimize")} onClick={() => runWindowAction(minimizeDesktopWindow)}>
          <Minus aria-hidden className="icon-button__icon" />
        </IconButton>
        <IconButton label={t("desktop.titlebar.maximize")} onClick={() => runWindowAction(toggleMaximizeDesktopWindow)}>
          <Maximize2 aria-hidden className="icon-button__icon" />
        </IconButton>
        <IconButton label={t("desktop.titlebar.close")} onClick={() => runWindowAction(closeDesktopWindow)}>
          <X aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
    </div>
  );
}

function HistoryDialog({
  entries,
  loading,
  onClose,
  onRefresh,
  onRevert,
  open,
}: {
  entries: ChatHistoryEntry[];
  loading: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onRevert: (userIndex: number) => void;
  open: boolean;
}) {
  const { t } = useI18n();
  return (
    <Dialog
      bodyClassName="chat-history-dialog__body"
      className="chat-history-dialog"
      closeLabel={t("common.close")}
      footer={
        <>
          <Button onClick={onRefresh}>{t("common.refresh")}</Button>
          <Button onClick={onClose}>{t("common.close")}</Button>
        </>
      }
      onClose={onClose}
      open={open}
      title={t("chat.history.title")}
    >
      {loading ? <p className="chat-history__empty">{t("chat.history.loading")}</p> : null}
      {!loading && entries.length === 0 ? <p className="chat-history__empty">{t("chat.history.empty")}</p> : null}
      {!loading && entries.length > 0 ? (
        <div className="chat-history__list">
          {entries.map((entry) => (
            <section className="chat-history__entry" data-role={entry.role} key={entry.id}>
              <p className="chat-history__text">{entry.text}</p>
              {entry.role === "user" && entry.revertUserIndex != null ? (
                <div className="chat-history__actions">
                  <Button
                    className="chat-history__revert"
                    icon={<RotateCcw aria-hidden className="button__icon" />}
                    onClick={() => onRevert(entry.revertUserIndex!)}
                  >
                    {t("chat.history.revert")}
                  </Button>
                </div>
              ) : null}
            </section>
          ))}
        </div>
      ) : null}
    </Dialog>
  );
}

function FloatingToolbar({
  asrPaused,
  closeLabel,
  hidden,
  hideCloseButton,
  open,
  onCloseSurface,
  onCommand,
  onOpenChange,
  onOpenHistory,
  status,
  transportMode,
  transportState,
  voiceLanguage,
}: {
  asrPaused: boolean;
  closeLabel: string;
  hidden: boolean;
  hideCloseButton: boolean;
  open: boolean;
  onCloseSurface: () => void;
  onCommand: (command: ChatCommand) => void;
  onOpenChange: (open: boolean) => void;
  onOpenHistory: () => void;
  status: string;
  transportMode: ChatTransportMode;
  transportState: ChatTransportState;
  voiceLanguage: string;
}) {
  const { t } = useI18n();
  if (hidden) {
    return null;
  }
  const transportText = transportStatusText(t, transportState, transportMode);
  const closeTools = (event: FocusEvent<HTMLDivElement>) => {
    const nextTarget = event.relatedTarget;
    if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
      onOpenChange(false);
    }
  };
  const closeToolsWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      onOpenChange(false);
    }
  };
  return (
    <div
      className="floating-toolbar"
      data-open={open ? "true" : "false"}
      data-transport-mode={transportMode}
      data-transport-state={transportState}
      onBlur={closeTools}
      onKeyDown={closeToolsWithKeyboard}
    >
      <div className="floating-toolbar__summary">
        <span className="floating-toolbar__meta">
          <span className="floating-toolbar__transport">{transportText}</span>
          <span className="floating-toolbar__status">{status}</span>
        </span>
        <IconButton
          aria-controls="chat-stage-toolbar-panel"
          aria-expanded={open}
          className="floating-toolbar__menu-trigger"
          label={t("chat.toolbar.tools")}
          onClick={() => onOpenChange(!open)}
        >
          <MoreHorizontal aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
      <div
        aria-hidden={!open}
        className="floating-toolbar__panel"
        hidden={!open}
        id="chat-stage-toolbar-panel"
      >
        <div className="floating-toolbar__actions">
          {hideCloseButton ? null : (
            <IconButton label={closeLabel} onClick={onCloseSurface}>
              <X aria-hidden className="icon-button__icon" />
            </IconButton>
          )}
          <IconButton label={t("chat.toolbar.reroll")} onClick={() => onCommand({ type: "reroll" })}>
            <RotateCcw aria-hidden className="icon-button__icon" />
          </IconButton>
          <IconButton label={t("chat.toolbar.copyHistory")} onClick={() => onCommand({ type: "copy-history" })}>
            <Copy aria-hidden className="icon-button__icon" />
          </IconButton>
          <IconButton label={t("chat.toolbar.openHistory")} onClick={onOpenHistory}>
            <History aria-hidden className="icon-button__icon" />
          </IconButton>
          <IconButton label={t("chat.toolbar.clearHistory")} onClick={() => onCommand({ type: "clear-history" })}>
            <Trash2 aria-hidden className="icon-button__icon" />
          </IconButton>
          <ChatThemePicker />
          <IconButton
            label={asrPaused ? t("chat.toolbar.resumeAsr") : t("chat.toolbar.pauseAsr")}
            onClick={() => onCommand({ type: asrPaused ? "resume-asr" : "pause-asr" })}
          >
            {asrPaused ? (
              <Mic aria-hidden className="icon-button__icon" />
            ) : (
              <MicOff aria-hidden className="icon-button__icon" />
            )}
          </IconButton>
          <ToolbarButton
            className="floating-toolbar__skip"
            icon={<SkipForward aria-hidden className="button__icon" />}
            onClick={() => onCommand({ type: "skip-speech" })}
          >
            {t("chat.toolbar.skipSpeech")}
          </ToolbarButton>
        </div>
        <label className="floating-toolbar__voice">
          <span className="visually-hidden">{t("template.field.voiceLanguage")}</span>
          <Languages aria-hidden className="floating-toolbar__voice-icon" />
          <Select
            aria-label={t("template.field.voiceLanguage")}
            className="floating-toolbar__voice-select"
            onChange={(event) => onCommand({ payload: event.target.value, type: "change-voice-language" })}
            value={voiceLanguage}
          >
            {chatVoiceLanguages.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.labelKey)}
              </option>
            ))}
          </Select>
        </label>
        <PluginSlot slot="chat-toolbar" />
      </div>
    </div>
  );
}

function InputLayer({
  disabled,
  hidden,
  onChange,
  onSubmit,
  value,
}: {
  disabled: boolean;
  hidden: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  value: string;
}) {
  const { language, t } = useI18n();
  const { showToast } = useToast();
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const transcriptBaseRef = useRef("");
  const valueRef = useRef(value);

  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  const stopListening = () => {
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (recognition) {
      recognition.stop();
    }
    setListening(false);
  };

  useEffect(() => {
    if (disabled && listening) {
      stopListening();
    }
  }, [disabled, listening]);

  useEffect(
    () => () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    },
    [],
  );

  const startListening = () => {
    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) {
      showToast({ kind: "error", message: t("chat.input.micUnsupported"), title: t("common.operationFailed") });
      return;
    }
    try {
      const recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = speechRecognitionLanguage(language);
      transcriptBaseRef.current = valueRef.current.trim();
      recognition.onresult = (event) => {
        let finalText = "";
        let interimText = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          const transcript = result[0]?.transcript ?? "";
          if (result.isFinal) {
            finalText += transcript;
          } else {
            interimText += transcript;
          }
        }
        if (finalText) {
          const next = appendTranscript(transcriptBaseRef.current, finalText, language);
          transcriptBaseRef.current = next;
          onChange(next);
        } else if (interimText) {
          onChange(appendTranscript(transcriptBaseRef.current, interimText, language));
        }
      };
      recognition.onerror = (event) => {
        recognitionRef.current = null;
        setListening(false);
        const denied = event.error === "not-allowed" || event.error === "service-not-allowed";
        if (event.error !== "no-speech") {
          showToast({
            kind: "error",
            message: denied ? t("chat.input.micDenied") : event.message || event.error || t("chat.input.micError"),
            title: t("common.operationFailed"),
          });
        }
      };
      recognition.onend = () => {
        recognitionRef.current = null;
        setListening(false);
      };
      recognitionRef.current = recognition;
      recognition.start();
      setListening(true);
    } catch (error) {
      recognitionRef.current = null;
      setListening(false);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.input.micError"),
        title: t("common.operationFailed"),
      });
    }
  };

  if (hidden) {
    return null;
  }

  return (
    <div className="input-layer" data-listening={listening ? "true" : "false"}>
      <TextArea
        className="input-layer__input"
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder={t("chat.input.placeholder")}
        value={value}
      />
      <IconButton
        className={["input-layer__mic", listening ? "input-layer__mic--active" : ""].filter(Boolean).join(" ")}
        disabled={disabled && !listening}
        label={listening ? t("chat.input.micStop") : t("chat.input.micStart")}
        onClick={() => {
          if (listening) {
            stopListening();
          } else {
            startListening();
          }
        }}
      >
        {listening ? (
          <MicOff aria-hidden className="icon-button__icon" />
        ) : (
          <Mic aria-hidden className="icon-button__icon" />
        )}
      </IconButton>
      <Button
        disabled={!value.trim() || disabled}
        icon={<Send aria-hidden className="button__icon" />}
        onClick={onSubmit}
        variant="primary"
      >
        {t("chat.input.send")}
      </Button>
    </div>
  );
}

export function ChatStagePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(chatStageReducer, emptyChatState);
  const [confirmClearHistory, setConfirmClearHistory] = useState(false);
  const [confirmRevertUserIndex, setConfirmRevertUserIndex] = useState<number | null>(null);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [toolbarOpen, setToolbarOpen] = useState(false);
  const [visibleDialogCharacters, setVisibleDialogCharacters] = useState(0);
  const { showToast } = useToast();
  const { t } = useI18n();
  const theme = useOptionalChatTheme();
  const themeStyle = theme?.style ?? {};
  const viewModel = useMemo(() => buildChatStageViewModel(state), [state]);
  const standaloneDesktopWindow = isTauriDesktop() && location.pathname === "/chat-stage";
  const transparentBackground = !viewModel.backgroundPath;
  const eventSeqRef = useRef(0);
  eventSeqRef.current = state.eventSeq;
  const pendingAnimatedDialogKeyRef = useRef<string | null>(null);
  const dialogSource = useMemo(
    () =>
      buildDialogTypewriterSource({
        characterName: viewModel.dialogCharacterName,
        html: viewModel.dialogHtml,
        text: viewModel.dialogText,
      }),
    [viewModel.dialogCharacterName, viewModel.dialogHtml, viewModel.dialogText],
  );
  const typewriterCps = theme?.resolved?.typewriter.cps ?? DEFAULT_TYPEWRITER_CPS;
  const displayedDialog = useMemo(
    () => renderDialogTypewriterFrame(dialogSource, visibleDialogCharacters),
    [dialogSource, visibleDialogCharacters],
  );
  const typingDialog = visibleDialogCharacters < dialogSource.totalCharacters;

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
    if (!viewModel.layers.toolbar) {
      setToolbarOpen(false);
    }
  }, [viewModel.layers.toolbar]);

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
        pendingAnimatedDialogKeyRef.current = buildDialogTypewriterSource({
          characterName: event.isSystem ? undefined : event.speaker,
          html: event.fullHtml,
        }).cacheKey;
        setVisibleDialogCharacters(0);
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
    sendCommand({ payload: text, type: "send-message" });
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

  return (
    <>
      <main className="chat-stage" data-background={transparentBackground ? "transparent" : "media"} style={themeStyle}>
        <StandaloneDesktopWindowControls hidden={!standaloneDesktopWindow} />
        <BackgroundLayer
          hidden={!viewModel.layers.background}
          path={viewModel.backgroundPath}
          transparent={transparentBackground}
        />
        <CgLayer hidden={!viewModel.layers.cg} path={viewModel.cgPath} />
        <SpriteLayer hidden={!viewModel.layers.sprites} sprites={viewModel.sprites} />
        <BusyLayer hidden={!viewModel.layers.busy} text={viewModel.busyText} />
        <NotificationLayer hidden={!viewModel.layers.notification} text={viewModel.notificationText} />
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
        <OptionsLayer
          hidden={!viewModel.layers.options}
          onSelect={(option) => sendCommand({ payload: option, type: "submit-option" })}
          options={viewModel.options}
        />
        <FloatingToolbar
          asrPaused={viewModel.status === "paused"}
          closeLabel={t(standaloneDesktopWindow ? "desktop.titlebar.close" : "chat.toolbar.close")}
          hidden={!viewModel.layers.toolbar}
          hideCloseButton={standaloneDesktopWindow}
          open={toolbarOpen}
          onCloseSurface={closeSurface}
          onCommand={sendCommand}
          onOpenChange={setToolbarOpen}
          onOpenHistory={openHistoryDialog}
          status={viewModel.statusText}
          transportMode={viewModel.transportMode}
          transportState={viewModel.transportState}
          voiceLanguage={viewModel.voiceLanguage || "ja"}
        />
        <InputLayer
          disabled={viewModel.inputDisabled}
          hidden={!viewModel.layers.input}
          onChange={(text) => dispatch({ text, type: "setDraft" })}
          onSubmit={submit}
          value={viewModel.inputDraft}
        />
      </main>
      <HistoryDialog
        entries={state.historyEntries ?? []}
        loading={historyLoading}
        onClose={() => setHistoryDialogOpen(false)}
        onRefresh={() => {
          void refreshHistory();
        }}
        onRevert={(userIndex) => setConfirmRevertUserIndex(userIndex)}
        open={historyDialogOpen}
      />
      <AlertDialog
        body={t("chat.clear.confirmBody")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("chat.clear.confirmAction")}
        onCancel={() => setConfirmClearHistory(false)}
        onConfirm={() => sendCommand({ type: "clear-history" })}
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
