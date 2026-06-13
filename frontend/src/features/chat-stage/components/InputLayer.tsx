import { useEffect, useRef, useState } from "react";
import { Mic, MicOff, Send } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { ChatCommand } from "../../../shared/platform/types";
import { Button, IconButton, TextArea, useToast } from "../../../shared/ui";
import {
  appendTranscript,
  getSpeechRecognitionConstructor,
  speechRecognitionLanguage,
  type BrowserSpeechRecognition,
} from "../speechRecognition";

export function InputLayer({
  asrPaused,
  disabled,
  hidden,
  onChange,
  onCommand,
  onSubmit,
  value,
}: {
  asrPaused: boolean;
  disabled: boolean;
  hidden: boolean;
  onChange: (value: string) => void;
  onCommand: (command: ChatCommand) => void;
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
    <div className="input-layer" data-chat-stage-hitbox="true" data-listening={listening ? "true" : "false"}>
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
      <div className="input-layer__voice-stack" role="group">
        <IconButton
          className={["input-layer__voice-button", "input-layer__mic", listening ? "input-layer__mic--active" : ""]
            .filter(Boolean)
            .join(" ")}
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
            <Mic aria-hidden className="icon-button__icon" />
          ) : (
            <MicOff aria-hidden className="icon-button__icon" />
          )}
        </IconButton>
      </div>
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
