import type { CSSProperties } from "react";

import { TRANSPARENT_BACKGROUND_NAME } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import { Select, Switch, type PageSectionProps } from "../../../shared/ui";
import { templateVoiceLanguages } from "../templateFlow";
import type { TemplateEditorContext } from "../templateContext";

export function TemplateStageSection({ ctx }: PageSectionProps<TemplateEditorContext>) {
  const { t } = useI18n();

  return (
    <>
      <label className="template-side-field">
        <span className="template-side-field__label">{t("template.field.background")}</span>
        <Select onChange={(event) => ctx.setSelectedBackground(event.target.value)} value={ctx.selectedBackground}>
          {ctx.backgroundOptions.map((name) => (
            <option key={name} value={name}>
              {name === TRANSPARENT_BACKGROUND_NAME ? t("template.transparentBackground") : name}
            </option>
          ))}
        </Select>
      </label>

      {ctx.effects.length > 0 ? (
        <div className="template-side-field template-effect-section">
          <span className="template-side-field__label">{t("template.field.effectName")}</span>
          <div aria-label={t("template.field.effectName")} className="template-effect-grid" role="group">
            {ctx.effects.map((effect) => {
              const isSelected = ctx.selectedEffectNames.has(effect.name);
              return (
                <button
                  aria-pressed={isSelected}
                  className={`template-character-card${isSelected ? " template-character-card--selected" : ""}`}
                  key={effect.name}
                  onClick={() => ctx.toggleEffect(effect.name, !isSelected)}
                  style={{ "--template-character-color": effect.color || "#5b8def" } as CSSProperties}
                  title={effect.name}
                  type="button"
                >
                  <span aria-hidden className="template-character-card__dot" />
                  <span className="template-character-card__name">{effect.name}</span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="template-side-field" data-standalone-gpu="true">
        <div className="template-sprite-heading">
          <label className="template-side-field__label" htmlFor="template-use-cg">
            {t("template.field.useCg")}
          </label>
          <Switch checked={ctx.useCg} id="template-use-cg" onChange={(event) => ctx.setUseCg(event.target.checked)} />
        </div>
      </div>

      <div className="template-side-field">
        <span className="template-side-field__label">{t("template.field.voiceLanguage")}</span>
        <div className="template-language-segments" role="group">
          {templateVoiceLanguages.map((option) => (
            <button
              aria-pressed={ctx.voiceLanguage === option.value}
              className={`template-language-segment${
                ctx.voiceLanguage === option.value ? " template-language-segment--active" : ""
              }`}
              key={option.value}
              onClick={() => ctx.handleVoiceLanguageChange(option.value)}
              type="button"
            >
              {t(option.labelKey)}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
