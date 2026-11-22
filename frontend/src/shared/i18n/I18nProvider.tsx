import { createContext, useContext, useEffect, useMemo } from "react";
import type { ReactNode } from "react";

import { frontendMessages } from "./messages";
import type { FrontendLanguage, MessageKey } from "./messages";

export type MessageValues = Record<string, string | number>;
export type TranslateFn = (key: MessageKey, values?: MessageValues) => string;

export interface I18nContextValue {
  language: FrontendLanguage;
  t: TranslateFn;
}

export const I18nContext = createContext<I18nContextValue | null>(null);

function interpolate(template: string, values?: MessageValues) {
  if (!values) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match,
  );
}

export function resolveDocumentLanguage(): FrontendLanguage {
  if (typeof document !== "undefined") {
    const raw = (document.documentElement.lang || "").trim().toLowerCase();
    if (raw === "en" || raw.startsWith("en-")) {
      return "en";
    }
    if (raw === "ja" || raw.startsWith("ja-")) {
      return "ja";
    }
  }
  return "zh_CN";
}

export function translateMessage(language: FrontendLanguage, key: MessageKey, values?: MessageValues) {
  return interpolate(frontendMessages[language][key] ?? frontendMessages.zh_CN[key] ?? key, values);
}

export function I18nProvider({ children, language }: { children: ReactNode; language: FrontendLanguage }) {
  useEffect(() => {
    document.documentElement.lang = language === "zh_CN" ? "zh-CN" : language;
  }, [language]);

  const value = useMemo<I18nContextValue>(
    () => ({
      language,
      t: (key, values) => translateMessage(language, key, values),
    }),
    [language],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error("useI18n must be used inside I18nProvider");
  }
  return value;
}

export function useOptionalI18n(): I18nContextValue {
  const value = useContext(I18nContext);
  return useMemo(() => {
    if (value) {
      return value;
    }
    const fallbackLanguage: FrontendLanguage = "zh_CN";
    return {
      language: fallbackLanguage,
      t: (key, values) => translateMessage(fallbackLanguage, key, values),
    };
  }, [value]);
}
