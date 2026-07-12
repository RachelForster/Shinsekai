import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Ear, EarOff, Mic, MicOff, Plus, Send } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { ChatCommand } from "../../../shared/platform/types";
import { Button, IconButton, TextArea, TextInput, useToast } from "../../../shared/ui";
import {
  appendTranscript,
  getSpeechRecognitionConstructor,
  speechRecognitionLanguage,
  type BrowserSpeechRecognition,
} from "../speechRecognition";
import { useDismissableLayer } from "../hooks/useDismissableLayer";
import { useAutoHideRegion } from "../hooks/useAutoHideRegion";

export function InputLayer({
  autoHide = false,
  asrPaused,
  disabled,
  hidden,
  inputLayout = "default",
  longPressTalkEnabled = false,
  onChange,
  onCommand,
  onSubmit,
  value,
}: {
  asrPaused: boolean;
  autoHide?: boolean;
  disabled: boolean;
  hidden: boolean;
  inputLayout?: "default" | "pill";
  longPressTalkEnabled?: boolean;
  onChange: (value: string) => void;
  onCommand: (command: ChatCommand) => void;
  onSubmit: () => void;
  value: string;
}) {
  const { language, t } = useI18n();
  const { showToast } = useToast();
  const [listening, setListening] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [holdTalkActive, setHoldTalkActive] = useState(false);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const holdTalkActiveRef = useRef(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const transcriptBaseRef = useRef("");
  const valueRef = useRef(value);
  const pillLayout = inputLayout === "pill";
  const pressToTalk = pillLayout && longPressTalkEnabled;
  const canSubmit = Boolean(value.trim()) && !disabled;
  const closePanel = useCallback(() => setPanelOpen(false), []);
  const forceVisible = Boolean(value.trim()) || listening || panelOpen || holdTalkActive;
  const autoHideRegion = useAutoHideRegion({ enabled: autoHide, forceVisible });

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
    <div
      ref={rootRef}
      className="input-layer"
      data-auto-hide={autoHide ? "true" : "false"}
      data-chat-stage-hitbox="true"
      data-force-visible={forceVisible ? "true" : "false"}
      data-layout={inputLayout}
      data-listening={listening ? "true" : "false"}
      data-panel-open={panelOpen ? "true" : "false"}
      data-visible={autoHideRegion.visible ? "true" : "false"}
      onBlurCapture={autoHideRegion.handleBlur}
      onFocusCapture={autoHideRegion.handleFocus}
      onPointerEnter={autoHideRegion.show}
      onPointerLeave={autoHideRegion.scheduleHide}
      style={autoHideRegion.visible ? undefined : { pointerEvents: "none" }}
    >
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
        {pillLayout ? (
          <TextInput
            autoComplete="off"
            className="input-layer__input input-layer__input--single"
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                onSubmit();
              }
            }}
            placeholder={t("chat.input.placeholder")}
            value={value}
          />
        ) : (
          <TextArea
            className="input-layer__input"
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                onSubmit();
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
            onClick={onSubmit}
            variant="primary"
          >
            {t("chat.input.send")}
          </Button>
        ) : null}
      </div>
      {pillLayout ? (
        <>
          <div className="input-layer__pill-actions" role="group">
            <IconButton
              className="input-layer__quick-submit"
              disabled={!canSubmit}
              label={t("chat.input.send")}
              onClick={onSubmit}
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
              aria-pressed={asrPaused}
              className="input-layer__panel-button"
              onClick={() => {
                onCommand({ type: asrPaused ? "resume-asr" : "pause-asr" });
                setPanelOpen(false);
              }}
              tabIndex={panelOpen ? undefined : -1}
              type="button"
            >
              {asrPaused ? (
                <Ear aria-hidden className="input-layer__panel-icon" />
              ) : (
                <EarOff aria-hidden className="input-layer__panel-icon" />
              )}
              <span>{asrPaused ? t("chat.toolbar.resumeAsr") : t("chat.toolbar.pauseAsr")}</span>
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
