import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Ear, EarOff, FileText, ImagePlus, Mic, MicOff, Plus, Send, X } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { ChatAttachmentInput, ChatCommand } from "../../../shared/platform/types";
import { Button, IconButton, TextArea, TextInput, ThemeFrame, useToast } from "../../../shared/ui";
import {
  appendTranscript,
  getSpeechRecognitionConstructor,
  SPEECH_RECOGNITION_RESTART_DELAY_MS,
  SPEECH_RECOGNITION_SILENCE_SUBMIT_MS,
  speechRecognitionLanguage,
  type BrowserSpeechRecognition,
} from "../speechRecognition";
import { useDismissableLayer } from "../hooks/useDismissableLayer";
import { useAutoHideRegion } from "../hooks/useAutoHideRegion";

export function InputLayer({
  attachments,
  autoHide = false,
  asrPaused,
  batchEnabled,
  disabled,
  hidden,
  inputLayout = "default",
  longPressTalkEnabled = false,
  onChange,
  onCommand,
  onFlushBatch,
  onInputActivity,
  onPickAttachments,
  onRemoveAttachment,
  onSubmit,
  value,
}: {
  asrPaused: boolean;
  attachments: ChatAttachmentInput[];
  autoHide?: boolean;
  batchEnabled: boolean;
  disabled: boolean;
  hidden: boolean;
  inputLayout?: "default" | "pill";
  longPressTalkEnabled?: boolean;
  onChange: (value: string) => void;
  onCommand: (command: ChatCommand) => void;
  onFlushBatch: () => void | Promise<void>;
  onInputActivity: (state: { composing: boolean; hasText: boolean }) => void;
  onSubmit: (textOverride?: string) => void | Promise<void>;
  onPickAttachments: (kind: ChatAttachmentInput["kind"]) => void;
  onRemoveAttachment: (attachment: ChatAttachmentInput) => void;
  value: string;
}) {
  const { language, t } = useI18n();
  const { showToast } = useToast();
  const [listening, setListening] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [holdTalkActive, setHoldTalkActive] = useState(false);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const recognitionRequestedRef = useRef(false);
  const restartTimerRef = useRef<number | null>(null);
  const silenceTimerRef = useRef<number | null>(null);
  const startRecognitionSessionRef = useRef<() => void>(() => undefined);
  const holdTalkActiveRef = useRef(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const transcriptBaseRef = useRef("");
  const valueRef = useRef(value);
  const disabledRef = useRef(disabled);
  const onSubmitRef = useRef(onSubmit);
  const inputActivityRef = useRef("");
  const pillLayout = inputLayout === "pill";
  const pressToTalk = pillLayout && longPressTalkEnabled;
  const canSubmit = Boolean(value.trim() || attachments.length) && !disabled;
  const closePanel = useCallback(() => setPanelOpen(false), []);
  const forceVisible = Boolean(value.trim() || attachments.length) || listening || panelOpen || holdTalkActive;
  const autoHideRegion = useAutoHideRegion({ active: !hidden, enabled: autoHide, forceVisible });

  useEffect(() => {
    valueRef.current = value;
    if (!value.trim()) {
      inputActivityRef.current = "false:false";
    }
  }, [value]);

  disabledRef.current = disabled;
  onSubmitRef.current = onSubmit;

  const reportInputActivity = (nextValue: string, composing: boolean) => {
    if (!batchEnabled) {
      return;
    }
    const activity = { composing, hasText: Boolean(nextValue.trim()) };
    const key = `${activity.hasText}:${activity.composing}`;
    if (inputActivityRef.current === key) {
      return;
    }
    inputActivityRef.current = key;
    onInputActivity(activity);
  };

  const handleInputChange = (nextValue: string) => {
    onChange(nextValue);
    reportInputActivity(nextValue, false);
  };

  const submitFromKeyboard = async (flushBatch: boolean) => {
    await onSubmit();
    if (flushBatch && batchEnabled) {
      await onFlushBatch();
    }
  };

  const clearRestartTimer = () => {
    if (restartTimerRef.current !== null) {
      window.clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
  };

  const clearSilenceTimer = () => {
    if (silenceTimerRef.current !== null) {
      window.clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  };

  const stopListening = () => {
    recognitionRequestedRef.current = false;
    clearRestartTimer();
    clearSilenceTimer();
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (recognition) {
      recognition.stop();
    }
    setListening(false);
  };

  const toggleListening = () => {
    if (listening) {
      stopListening();
    } else {
      startListening();
    }
  };

  const stopHoldTalk = (event?: KeyboardEvent<HTMLButtonElement> | PointerEvent<HTMLButtonElement>) => {
    if (!holdTalkActiveRef.current) {
      return;
    }
    event?.preventDefault();
    holdTalkActiveRef.current = false;
    setHoldTalkActive(false);
    onCommand({ type: "pause-asr" });
  };

  const startHoldTalk = (event: KeyboardEvent<HTMLButtonElement> | PointerEvent<HTMLButtonElement>) => {
    if (!pressToTalk || disabled || holdTalkActiveRef.current) {
      return;
    }
    event.preventDefault();
    holdTalkActiveRef.current = true;
    setHoldTalkActive(true);
    onCommand({ type: "resume-asr" });
  };

  useEffect(() => {
    if (disabled && listening) {
      stopListening();
    }
  }, [disabled, listening]);

  useEffect(() => {
    if (!pressToTalk || disabled) {
      stopHoldTalk();
    }
  }, [disabled, pressToTalk]);

  useDismissableLayer({ active: panelOpen, onDismiss: closePanel, rootRef });

  useEffect(() => {
    if (hidden || !pillLayout) {
      setPanelOpen(false);
    }
  }, [hidden, pillLayout]);

  useEffect(
    () => () => {
      recognitionRequestedRef.current = false;
      clearRestartTimer();
      clearSilenceTimer();
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    },
    [],
  );

  const scheduleSilenceSubmit = () => {
    clearSilenceTimer();
    silenceTimerRef.current = window.setTimeout(() => {
      silenceTimerRef.current = null;
      const text = valueRef.current.trim();
      if (!recognitionRequestedRef.current || disabledRef.current || !text) {
        return;
      }
      stopListening();
      void onSubmitRef.current(text);
    }, SPEECH_RECOGNITION_SILENCE_SUBMIT_MS);
  };

  const startRecognitionSession = () => {
    if (!recognitionRequestedRef.current || disabledRef.current || recognitionRef.current) {
      return;
    }
    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) {
      recognitionRequestedRef.current = false;
      setListening(false);
      showToast({ kind: "error", message: t("chat.input.micUnsupported"), title: t("common.operationFailed") });
      return;
    }
    try {
      const recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = speechRecognitionLanguage(language);
      recognition.onresult = (event) => {
        if (!recognitionRequestedRef.current || recognitionRef.current !== recognition) {
          return;
        }
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
          const displayed = interimText ? appendTranscript(next, interimText, language) : next;
          valueRef.current = displayed;
          onChange(displayed);
        } else if (interimText) {
          const displayed = appendTranscript(transcriptBaseRef.current, interimText, language);
          valueRef.current = displayed;
          onChange(displayed);
        }
        if (finalText || interimText) {
          scheduleSilenceSubmit();
        }
      };
      recognition.onerror = (event) => {
        if (recognitionRef.current !== recognition) {
          return;
        }
        const denied = event.error === "not-allowed" || event.error === "service-not-allowed";
        const retryable = event.error === "no-speech";
        if (!retryable) {
          recognitionRequestedRef.current = false;
          recognitionRef.current = null;
          clearRestartTimer();
          clearSilenceTimer();
          setListening(false);
        }
        if (!retryable && event.error !== "aborted") {
          showToast({
            kind: "error",
            message: denied ? t("chat.input.micDenied") : event.message || event.error || t("chat.input.micError"),
            title: t("common.operationFailed"),
          });
        }
      };
      recognition.onend = () => {
        if (recognitionRef.current !== recognition) {
          return;
        }
        recognitionRef.current = null;
        if (!recognitionRequestedRef.current || disabledRef.current) {
          setListening(false);
          return;
        }
        clearRestartTimer();
        restartTimerRef.current = window.setTimeout(() => {
          restartTimerRef.current = null;
          startRecognitionSessionRef.current();
        }, SPEECH_RECOGNITION_RESTART_DELAY_MS);
      };
      recognitionRef.current = recognition;
      recognition.start();
      setListening(true);
    } catch (error) {
      recognitionRequestedRef.current = false;
      recognitionRef.current = null;
      setListening(false);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.input.micError"),
        title: t("common.operationFailed"),
      });
    }
  };

  startRecognitionSessionRef.current = startRecognitionSession;

  const startListening = () => {
    if (!getSpeechRecognitionConstructor()) {
      showToast({ kind: "error", message: t("chat.input.micUnsupported"), title: t("common.operationFailed") });
      return;
    }
    recognitionRequestedRef.current = true;
    transcriptBaseRef.current = valueRef.current.trim();
    setListening(true);
    startRecognitionSessionRef.current();
  };

  if (hidden) {
    return null;
  }

  return (
    <div
      ref={rootRef}
      className="input-layer"
      data-auto-hide={autoHide ? "true" : "false"}
      data-chat-stage-hitbox="true"
      data-force-visible={forceVisible ? "true" : "false"}
      data-layout={inputLayout}
      data-listening={listening ? "true" : "false"}
      data-has-attachments={attachments.length ? "true" : "false"}
      data-panel-open={panelOpen ? "true" : "false"}
      data-visible={autoHideRegion.visible ? "true" : "false"}
      onBlurCapture={autoHideRegion.handleBlur}
      onFocusCapture={autoHideRegion.handleFocus}
      onPointerEnter={autoHideRegion.show}
      onPointerLeave={autoHideRegion.scheduleHide}
      style={autoHideRegion.visible ? undefined : { pointerEvents: "none" }}
    >
      <ThemeFrame prefix="chat-input" />
      {pillLayout ? (
        <IconButton
          className="input-layer__press"
          data-active={holdTalkActive || listening ? "true" : "false"}
          disabled={pressToTalk ? disabled : disabled && !listening}
          label={
            pressToTalk ? t("chat.input.holdToTalk") : listening ? t("chat.input.micStop") : t("chat.input.micStart")
          }
          onBlur={() => stopHoldTalk()}
          onClick={(event) => {
            if (pressToTalk) {
              event.preventDefault();
              return;
            }
            toggleListening();
          }}
          onKeyDown={(event) => {
            if ((event.key === " " || event.key === "Enter") && !event.repeat) {
              startHoldTalk(event);
            }
          }}
          onKeyUp={(event) => {
            if (event.key === " " || event.key === "Enter") {
              stopHoldTalk(event);
            }
          }}
          onLostPointerCapture={(event) => stopHoldTalk(event)}
          onPointerCancel={(event) => stopHoldTalk(event)}
          onPointerDown={(event) => {
            if (pressToTalk) {
              event.currentTarget.setPointerCapture?.(event.pointerId);
              startHoldTalk(event);
            }
          }}
          onPointerLeave={(event) => stopHoldTalk(event)}
          onPointerUp={(event) => stopHoldTalk(event)}
        >
          {pressToTalk || !listening ? (
            <Mic aria-hidden className="icon-button__icon" />
          ) : (
            <MicOff aria-hidden className="icon-button__icon" />
          )}
        </IconButton>
      ) : null}
      <div className="input-layer__field">
        {attachments.length ? (
          <div aria-label={t("chat.input.attachments")} className="input-layer__attachments">
            {attachments.map((attachment) => (
              <button
                aria-label={t("chat.input.removeAttachment", { name: attachment.name })}
                className="input-layer__attachment"
                data-kind={attachment.kind}
                disabled={disabled}
                key={`${attachment.kind}:${attachment.path}`}
                onClick={() => onRemoveAttachment(attachment)}
                title={attachment.name}
                type="button"
              >
                <span className="input-layer__attachment-name">{attachment.name}</span>
                <X aria-hidden className="input-layer__attachment-remove" />
              </button>
            ))}
          </div>
        ) : null}
        {pillLayout ? (
          <TextInput
            autoComplete="off"
            className="input-layer__input input-layer__input--single"
            disabled={disabled}
            onChange={(event) => handleInputChange(event.target.value)}
            onCompositionEnd={(event) => reportInputActivity(event.currentTarget.value, false)}
            onCompositionStart={(event) => reportInputActivity(event.currentTarget.value, true)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void submitFromKeyboard(event.ctrlKey);
              }
            }}
            placeholder={t("chat.input.placeholder")}
            value={value}
          />
        ) : (
          <TextArea
            className="input-layer__input"
            disabled={disabled}
            onChange={(event) => handleInputChange(event.target.value)}
            onCompositionEnd={(event) => reportInputActivity(event.currentTarget.value, false)}
            onCompositionStart={(event) => reportInputActivity(event.currentTarget.value, true)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void submitFromKeyboard(event.ctrlKey);
              }
            }}
            placeholder={t("chat.input.placeholder")}
            value={value}
          />
        )}
        {!pillLayout ? (
          <Button
            aria-label={t("chat.input.send")}
            className="input-layer__send"
            disabled={!canSubmit}
            icon={<Send aria-hidden className="button__icon" />}
            onClick={() => void onSubmit()}
            variant="primary"
          >
            {t("chat.input.send")}
          </Button>
        ) : null}
      </div>
      {!pillLayout ? (
        <div aria-label={t("chat.input.attachments")} className="input-layer__attachment-stack" role="group">
          <IconButton
            className="input-layer__attachment-button"
            disabled={disabled}
            label={t("chat.input.attachImage")}
            onClick={() => onPickAttachments("image")}
          >
            <ImagePlus aria-hidden className="icon-button__icon" />
          </IconButton>
          <IconButton
            className="input-layer__attachment-button"
            disabled={disabled}
            label={t("chat.input.attachFile")}
            onClick={() => onPickAttachments("file")}
          >
            <FileText aria-hidden className="icon-button__icon" />
          </IconButton>
        </div>
      ) : null}
      {pillLayout ? (
        <>
          <div className="input-layer__pill-actions" role="group">
            <IconButton
              className="input-layer__quick-submit"
              disabled={!canSubmit}
              label={t("chat.input.send")}
              onClick={() => void onSubmit()}
            >
              <Send aria-hidden className="icon-button__icon" />
            </IconButton>
            <IconButton
              aria-expanded={panelOpen}
              className="input-layer__extra-toggle"
              label={t("chat.input.moreActions")}
              onClick={() => setPanelOpen((current) => !current)}
            >
              <Plus aria-hidden className="icon-button__icon" />
            </IconButton>
          </div>
          <div
            aria-hidden={!panelOpen}
            className="input-layer__panel"
            data-open={panelOpen ? "true" : "false"}
            role="group"
          >
            <button
              className="input-layer__panel-button"
              disabled={disabled}
              onClick={() => {
                setPanelOpen(false);
                onPickAttachments("image");
              }}
              tabIndex={panelOpen ? undefined : -1}
              type="button"
            >
              <ImagePlus aria-hidden className="input-layer__panel-icon" />
              <span>{t("chat.input.attachImage")}</span>
            </button>
            <button
              className="input-layer__panel-button"
              disabled={disabled}
              onClick={() => {
                setPanelOpen(false);
                onPickAttachments("file");
              }}
              tabIndex={panelOpen ? undefined : -1}
              type="button"
            >
              <FileText aria-hidden className="input-layer__panel-icon" />
              <span>{t("chat.input.attachFile")}</span>
            </button>
          </div>
        </>
      ) : null}
      {!pillLayout ? (
        <div className="input-layer__voice-stack" role="group">
          <IconButton
            className={["input-layer__voice-button", "input-layer__mic", listening ? "input-layer__mic--active" : ""]
              .filter(Boolean)
              .join(" ")}
            disabled={disabled && !listening}
            label={listening ? t("chat.input.micStop") : t("chat.input.micStart")}
            onClick={toggleListening}
          >
            {listening ? (
              <MicOff aria-hidden className="icon-button__icon" />
            ) : (
              <Mic aria-hidden className="icon-button__icon" />
            )}
          </IconButton>
          <IconButton
            aria-pressed={asrPaused}
            className={[
              "input-layer__voice-button",
              "input-layer__asr-toggle",
              asrPaused ? "input-layer__asr-toggle--paused" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            disabled={disabled}
            label={asrPaused ? t("chat.toolbar.resumeAsr") : t("chat.toolbar.pauseAsr")}
            onClick={() => onCommand({ type: asrPaused ? "resume-asr" : "pause-asr" })}
          >
            {asrPaused ? (
              <Ear aria-hidden className="icon-button__icon" />
            ) : (
              <EarOff aria-hidden className="icon-button__icon" />
            )}
          </IconButton>
        </div>
      ) : null}
    </div>
  );
}
