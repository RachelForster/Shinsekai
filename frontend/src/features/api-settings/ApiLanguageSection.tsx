import { useEffect, useState } from "react";
import type { SystemConfig } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { Select, Switch } from "../../shared/ui";
import { normalizeUiLanguage, type UiLanguage } from "./apiSettingsUtils";

function readColorScheme(): "light" | "dark" {
  const stored = localStorage.getItem("shinsekai-color-scheme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyColorScheme(scheme: "light" | "dark") {
  document.documentElement.setAttribute("data-color-scheme", scheme);
  localStorage.setItem("shinsekai-color-scheme", scheme);
}

interface ApiLanguageSectionProps {
  disabled: boolean;
  onChange: (language: UiLanguage) => void;
  systemDraft: SystemConfig;
}

export function ApiLanguageSection({ disabled, onChange, systemDraft }: ApiLanguageSectionProps) {
  const { t } = useI18n();
  const [darkMode, setDarkMode] = useState(() => readColorScheme() === "dark");

  useEffect(() => {
    applyColorScheme(darkMode ? "dark" : "light");
  }, [darkMode]);

  const uiLanguageOptions: Array<{ label: string; value: UiLanguage }> = [
    { label: t("api.language.zh"), value: "zh_CN" },
    { label: t("api.language.en"), value: "en" },
    { label: t("api.language.ja"), value: "ja" },
  ];
  return (
    <details className="section schema-section" open>
      <summary className="schema-section__summary">{t("api.language.title")}</summary>
      <div className="form-grid form-grid--two">
        <label className="field-row">
          <span className="field-row__label">{t("api.language.field")}</span>
          <span className="field-row__control">
            <Select
              disabled={disabled}
              onChange={(e) => onChange(normalizeUiLanguage(e.target.value as UiLanguage))}
              value={systemDraft.ui_language}
            >
              {uiLanguageOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("api.language.darkMode")}</span>
          <span className="field-row__control">
            <Switch checked={darkMode} onChange={(e) => setDarkMode(e.target.checked)} />
          </span>
        </label>
      </div>
    </details>
  );
}
