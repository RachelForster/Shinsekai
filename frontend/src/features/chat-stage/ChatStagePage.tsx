import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Copy, History, Mic, MicOff, RotateCcw, Send, SkipForward, Trash2 } from "lucide-react";

import { getChatSnapshot, getChatTheme, sendChatCommand, subscribeChat } from "../../entities/chat/repository";
import { PluginSlot } from "../../entities/plugin/slots";
import { useI18n } from "../../shared/i18n";
import type { ChatCommand, ChatSnapshot, ChatSprite } from "../../shared/platform/types";
import { parseChatChromeTheme } from "../../shared/theme/chatChromeTheme";
import type { ChatThemePayload } from "../../shared/theme/chatChromeTheme";
import { AlertDialog, Button, IconButton, TextArea, ToolbarButton, useToast } from "../../shared/ui";
import { chatStageReducer, emptyChatState } from "./chatState";

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

function BackgroundLayer({ path }: { path?: string }) {
  return (
    <div className="chat-stage__background">
      {path ? <img alt="" src={path} /> : <div className="chat-stage__fallback">Background</div>}
    </div>
  );
}

function SpriteLayer({ sprites }: { sprites: ChatSprite[] }) {
  return (
    <div className="sprite-layer">
      {sprites.map((sprite) => (
        <figure className="sprite-layer__figure" key={sprite.id}>
          <img alt={sprite.label} className="sprite-layer__image" src={sprite.path} />
        </figure>
      ))}
    </div>
  );
}

function DialogLayer({ characterName, text }: { characterName?: string; text: string }) {
  const { t } = useI18n();
  return (
    <section aria-live="polite" className="dialog-layer">
      {characterName ? <p className="dialog-layer__name">{characterName}</p> : null}
      <p className="dialog-layer__text">{text || t("chat.emptyDialog")}</p>
      <PluginSlot slot="chat-output" />
    </section>
  );
}

function OptionsLayer({ onSelect, options }: { onSelect: (option: string) => void; options: string[] }) {
  if (!options.length) {
    return null;
  }
  return (
    <div className="options-layer">
      {options.map((option) => (
        <Button className="options-layer__button" key={option} onClick={() => onSelect(option)}>
          {option}
        </Button>
      ))}
    </div>
  );
}

function FloatingToolbar({ onCommand, status }: { onCommand: (command: ChatCommand) => void; status: string }) {
  const { t } = useI18n();
  return (
    <div className="floating-toolbar">
      <IconButton label={t("chat.toolbar.reroll")} onClick={() => onCommand({ type: "reroll" })}>
        <RotateCcw aria-hidden className="icon-button__icon" />
      </IconButton>
      <IconButton label={t("chat.toolbar.copyHistory")} onClick={() => onCommand({ type: "copy-history" })}>
        <Copy aria-hidden className="icon-button__icon" />
      </IconButton>
      <IconButton label={t("chat.toolbar.openHistory")} onClick={() => onCommand({ type: "open-history" })}>
        <History aria-hidden className="icon-button__icon" />
      </IconButton>
      <IconButton label={t("chat.toolbar.clearHistory")} onClick={() => onCommand({ type: "clear-history" })}>
        <Trash2 aria-hidden className="icon-button__icon" />
      </IconButton>
      <IconButton label={t("chat.toolbar.pauseAsr")} onClick={() => onCommand({ type: "pause-asr" })}>
        <MicOff aria-hidden className="icon-button__icon" />
      </IconButton>
      <ToolbarButton
        icon={<SkipForward aria-hidden className="button__icon" />}
        onClick={() => onCommand({ type: "skip-speech" })}
      >
        {t("chat.toolbar.skipSpeech")}
      </ToolbarButton>
      <span className="floating-toolbar__status">{status}</span>
      <PluginSlot slot="chat-toolbar" />
    </div>
  );
}

function InputLayer({
  disabled,
  onChange,
  onSubmit,
  value,
}: {
  disabled: boolean;
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

  return (
    <div className="input-layer">
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
  const [state, dispatch] = useReducer(chatStageReducer, emptyChatState);
  const [themePayload, setThemePayload] = useState<ChatThemePayload | null>(null);
  const [confirmClearHistory, setConfirmClearHistory] = useState(false);
  const { showToast } = useToast();
  const { t } = useI18n();
  const themeStyle = useMemo(() => parseChatChromeTheme(themePayload), [themePayload]);

  useEffect(() => {
    let mounted = true;
    getChatTheme()
      .then((theme) => {
        if (mounted) {
          setThemePayload(theme);
        }
      })
      .catch(() => {
        if (mounted) {
          setThemePayload(null);
        }
      });
    getChatSnapshot()
      .then((snapshot: ChatSnapshot) => {
        if (mounted) {
          dispatch({ snapshot, type: "hydrate" });
        }
      })
      .catch((error) => {
        dispatch({ message: error instanceof Error ? error.message : t("chat.error.loadFallback"), type: "error" });
      });
    const unsubscribe = subscribeChat((snapshot) => dispatch({ snapshot, type: "hydrate" }));
    return () => {
      mounted = false;
      unsubscribe();
    };
  }, [t]);

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
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.error.commandFallback"),
        title: t("common.operationFailed"),
      });
    }
  };

  const submit = () => {
    const text = state.inputDraft.trim();
    if (!text) {
      return;
    }
    dispatch({ status: "generating", type: "setStatus" });
    sendCommand({ payload: text, type: "send-message" });
  };

  return (
    <>
      <main className="chat-stage" style={themeStyle}>
        <BackgroundLayer path={state.backgroundPath} />
        <SpriteLayer sprites={state.sprites} />
        <DialogLayer characterName={state.characterName} text={state.error ?? state.dialogText} />
        <OptionsLayer
          onSelect={(option) => sendCommand({ payload: option, type: "submit-option" })}
          options={state.options}
        />
        <FloatingToolbar onCommand={sendCommand} status={state.numericInfo ?? state.status} />
        <InputLayer
          disabled={state.status === "generating" || state.status === "streaming"}
          onChange={(text) => dispatch({ text, type: "setDraft" })}
          onSubmit={submit}
          value={state.inputDraft}
        />
      </main>
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
    </>
  );
}
