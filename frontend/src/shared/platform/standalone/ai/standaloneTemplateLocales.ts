import generatedLocales from "./generatedTemplateLocales.json";

export type StandaloneTemplateLocale = "zh_CN" | "en" | "ja";
export type StandaloneTemplateKey = keyof (typeof generatedLocales)["zh_CN"];

const LOCALE_TABLES: Record<StandaloneTemplateLocale, Record<StandaloneTemplateKey, string>> = generatedLocales;

export function resolveStandaloneTemplateLocale(uiLanguage?: string): StandaloneTemplateLocale {
  const norm = (uiLanguage ?? "").trim().toLowerCase().replace(/-/g, "_");
  if (norm.startsWith("en")) return "en";
  if (norm.startsWith("ja")) return "ja";
  return "zh_CN";
}

export function formatTemplateString(template: string, params?: Record<string, string | number>): string {
  return template.replace(/\{\{|\}\}|\{([a-zA-Z0-9_]+)\}/g, (match, key?: string) => {
    if (match === "{{") return "{";
    if (match === "}}") return "}";
    if (key && params && params[key] !== undefined) {
      return String(params[key]);
    }
    return match;
  });
}

export function createStandaloneTemplateTranslator(uiLanguage?: string) {
  const table = LOCALE_TABLES[resolveStandaloneTemplateLocale(uiLanguage)];
  return (key: StandaloneTemplateKey, params?: Record<string, string | number>): string => {
    const raw = table[key] ?? generatedLocales.zh_CN[key];
    return formatTemplateString(raw, params);
  };
}
