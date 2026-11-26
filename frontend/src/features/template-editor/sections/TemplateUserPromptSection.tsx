import { RotateCcw } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { Button, TextArea, type PageSectionProps } from "../../../shared/ui";
import type { TemplateEditorContext } from "../templateContext";

export function TemplateUserPromptSection({ ctx }: PageSectionProps<TemplateEditorContext>) {
  const { t } = useI18n();

  return (
    <section className="template-user-prompt-card" data-section="user-prompt">
      <div className="template-summary-bar__header">
        <div className="template-summary-bar__title-group">
          <label className="template-panel__label" htmlFor="template-user-prompt">
            {t("template.bar.userPrompt")}
          </label>
          <span className="template-summary-pill">{t(ctx.scenarioStatusKey)}</span>
          {ctx.resolvedSelectedPresets.length > 0 ? (
            <span className="template-summary-pill">
              {t("template.bar.presetsAppendHint", { count: ctx.resolvedSelectedPresets.length })}
            </span>
          ) : null}
        </div>
        <Button
          icon={<RotateCcw aria-hidden className="button__icon" />}
          onClick={ctx.restoreDefaultScenario}
          variant="ghost"
        >
          {t("template.presets.restoreDefaultScenario")}
        </Button>
      </div>
      <TextArea
        className="template-scenario-textarea"
        id="template-user-prompt"
        onChange={(event) => {
          ctx.setSessionDraftActive(true);
          ctx.updateDraft({ baseScenario: event.target.value });
        }}
        placeholder={t("template.presets.basePromptPlaceholder")}
        rows={6}
        value={ctx.baseScenario}
      />
    </section>
  );
}
