import { createContext, useContext, useEffect, useMemo } from "react";
import type { ReactNode } from "react";

import { frontendMessages } from "./messages";
import type { FrontendLanguage, MessageKey } from "./messages";

type MessageValues = Record<string, string | number>;

interface I18nContextValue {
  language: FrontendLanguage;
  t: (key: MessageKey, values?: MessageValues) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

function interpolate(template: string, values?: MessageValues) {
  if (!values) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match,
  );
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

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error("useI18n must be used inside I18nProvider");
  }
  return value;
}
