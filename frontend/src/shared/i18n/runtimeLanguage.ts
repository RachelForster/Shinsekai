import { translateMessage, type MessageValues } from "./I18nProvider";
import type { FrontendLanguage, MessageKey } from "./messages";

let activeFrontendLanguage: FrontendLanguage = "zh_CN";

export function normalizeFrontendLanguage(value: string | undefined | null): FrontendLanguage {
  const clean = (value ?? "").trim().toLowerCase();
  if (clean === "en" || clean.startsWith("en-") || clean.startsWith("en_")) {
    return "en";
  }
  if (clean === "ja" || clean.startsWith("ja-") || clean.startsWith("ja_")) {
    return "ja";
  }
  return "zh_CN";
}

export function getActiveFrontendLanguage(): FrontendLanguage {
  return activeFrontendLanguage;
}

export function setActiveFrontendLanguage(language: string | undefined | null): FrontendLanguage {
  activeFrontendLanguage = normalizeFrontendLanguage(language);
  return activeFrontendLanguage;
}

export function translateRuntimeMessage(
  key: MessageKey,
  values?: MessageValues,
  languageOverride?: string | null,
): string {
  const lang = languageOverride ? normalizeFrontendLanguage(languageOverride) : activeFrontendLanguage;
  return translateMessage(lang, key, values);
}
