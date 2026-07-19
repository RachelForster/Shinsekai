export interface BrowserSpeechRecognition {
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

export const SPEECH_RECOGNITION_RESTART_DELAY_MS = 100;
export const SPEECH_RECOGNITION_SILENCE_SUBMIT_MS = 2_000;

export function getSpeechRecognitionConstructor(): BrowserSpeechRecognitionConstructor | null {
  const scope = window as typeof window & {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

export function speechRecognitionLanguage(language: string) {
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

export function appendTranscript(base: string, transcript: string, language: string) {
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
