import {
  LANG_ALIAS_AUTO_TOKENS,
  LANG_ALIAS_CHINESE_ZH,
  LANG_ALIAS_ENGLISH_ZH,
  LANG_ALIAS_KOREAN_TOKENS,
} from "../../../constants";
import type { Character } from "../../slices/characterTypes";

export type VoiceTargetKey = "ja" | "en" | "zh" | "yue" | "ko";

const AUTO_TOKENS = new Set<string>(LANG_ALIAS_AUTO_TOKENS);
const KOREAN_TOKENS = new Set<string>(["ko", "ko_kr", "korean", "all_ko", ...LANG_ALIAS_KOREAN_TOKENS]);

export function normalizeVoiceLanguageCode(raw?: string | null): string {
  const clean = String(raw ?? "").trim();
  if (!clean) return "";
  const low = clean.toLowerCase().replace(/-/g, "_");
  if (AUTO_TOKENS.has(low)) return "auto";
  if (
    low === "yue" ||
    low === "yue_hk" ||
    low === "cantonese" ||
    low === "cht" ||
    low === "zh_hk" ||
    low === "all_yue"
  ) {
    return "yue";
  }
  if (KOREAN_TOKENS.has(low)) {
    return "ko";
  }
  if (low.startsWith("en") || low === "english" || low === "all_en" || low === LANG_ALIAS_ENGLISH_ZH) {
    return "en";
  }
  if (
    low.startsWith("zh") ||
    low === "chinese" ||
    low === "cn" ||
    low === "cmn" ||
    low === "all_zh" ||
    low === LANG_ALIAS_CHINESE_ZH
  ) {
    return "zh";
  }
  if (low.startsWith("ja") || low === "jp" || low === "japanese" || low === "all_ja") {
    return "ja";
  }
  return low;
}

export function inferLanguageFromText(text?: string | null): VoiceTargetKey | "" {
  const sample = String(text ?? "").trim();
  if (!sample) return "";
  if (/[\u3040-\u30ff]/.test(sample)) return "ja";
  if (/[\u4e00-\u9fff]/.test(sample)) return "zh";
  if (/[\uac00-\ud7af]/.test(sample)) return "ko";
  if (/[A-Za-z]/.test(sample)) return "en";
  return "";
}

export function targetVoiceKey(code?: string | null): VoiceTargetKey | "auto" {
  const normalized = normalizeVoiceLanguageCode(code);
  if (normalized === "auto") return "auto";
  if (
    normalized === "yue" ||
    normalized === "en" ||
    normalized === "zh" ||
    normalized === "ja" ||
    normalized === "ko"
  ) {
    return normalized;
  }
  return "ja";
}

export function resolveCharacterVoiceLanguage(
  voiceLanguage: string | null | undefined,
  options: {
    promptLang?: string | null;
    promptText?: string | null;
    speechText?: string | null;
    fallback?: string;
  } = {},
): string {
  const fallback = options.fallback ?? "ja";
  const raw = String(voiceLanguage ?? "").trim();
  if (normalizeVoiceLanguageCode(raw) !== "auto") {
    return raw || fallback;
  }

  const refLang = normalizeVoiceLanguageCode(options.promptLang);
  if (refLang && refLang !== "auto") {
    return refLang;
  }

  const fromPrompt = inferLanguageFromText(options.promptText);
  if (fromPrompt) {
    return fromPrompt;
  }

  const fromSpeech = inferLanguageFromText(options.speechText);
  if (fromSpeech) {
    return fromSpeech;
  }

  return fallback;
}

export function resolveCastVoiceTarget(
  voiceLanguage: string | undefined,
  characters: Character[],
  uiLanguage?: string,
): { target: VoiceTargetKey | "auto"; perChar: Array<{ name: string; key: VoiceTargetKey }> } {
  if (normalizeVoiceLanguageCode(voiceLanguage) !== "auto") {
    return { target: targetVoiceKey(voiceLanguage || "ja"), perChar: [] };
  }
  const perChar: Array<{ name: string; key: VoiceTargetKey }> = [];
  for (const char of characters) {
    const byPrompt = normalizeVoiceLanguageCode(char.prompt_lang);
    const resolved = byPrompt && byPrompt !== "auto" ? byPrompt : inferLanguageFromText(char.prompt_text);
    const key = resolved ? targetVoiceKey(resolved) : "";
    if (key && key !== "auto") {
      perChar.push({ name: char.name, key });
    }
  }
  const distinct = new Set(perChar.map((item) => item.key));
  if (distinct.size === 1) {
    return { target: perChar[0].key, perChar };
  }
  if (distinct.size === 0) {
    return { target: targetVoiceKey(uiLanguage || "zh_CN"), perChar: [] };
  }
  return { target: "auto", perChar };
}

export function isUiVoiceSameLanguage(
  uiLanguage: string | undefined,
  resolvedTarget: VoiceTargetKey | "auto",
): boolean {
  if (resolvedTarget === "auto") return false;
  const uiMain =
    String(uiLanguage ?? "zh_CN")
      .trim()
      .split(/[-_]/)[0]
      .toLowerCase() || "zh";
  return uiMain === resolvedTarget;
}
