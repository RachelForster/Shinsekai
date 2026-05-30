import type { SystemConfig } from "../../entities/config/types";
import type { FormGroupSchema } from "../../shared/form-schema";
import { useI18n } from "../../shared/i18n";
import { SchemaFieldGrid } from "../../shared/ui";
import { normalizeUiLanguage, type UiLanguage } from "./apiSettingsUtils";

interface ApiLanguageSectionProps {
  disabled: boolean;
  onChange: (language: UiLanguage) => void;
  systemDraft: SystemConfig;
}

export function ApiLanguageSection({ disabled, onChange, systemDraft }: ApiLanguageSectionProps) {
  const { t } = useI18n();
  const uiLanguageOptions: Array<{ label: string; value: UiLanguage }> = [
    { label: t("api.language.zh"), value: "zh_CN" },
    { label: t("api.language.en"), value: "en" },
    { label: t("api.language.ja"), value: "ja" },
  ];
  const apiLanguageGroup: FormGroupSchema<SystemConfig> = {
    columns: 1,
    fields: [
      {
        label: t("api.language.field"),
        name: "ui_language",
        options: uiLanguageOptions,
        type: "select",
      },
    ],
    id: "api-language",
    title: t("api.language.title"),
  };

  return (
    <section className="section api-page__language">
      <div className="section__header">
        <div>
          <h2 className="section__title">{t("api.language.title")}</h2>
        </div>
      </div>
      <SchemaFieldGrid
        disabled={disabled}
        group={apiLanguageGroup}
        onChange={(nextSystem) => onChange(normalizeUiLanguage(nextSystem.ui_language))}
        value={systemDraft}
      />
      <p className="section__description">{t("api.language.hint")}</p>
    </section>
  );
}
