import type { CSSProperties } from "react";
import { Pencil } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { Button, type PageSectionProps } from "../../../shared/ui";
import { UserPromptPresetsDialog } from "../UserPromptPresetsDialog";
import type { TemplateEditorContext } from "../templateContext";

export function TemplatePresetPromptsSection({ ctx }: PageSectionProps<TemplateEditorContext>) {
  const { t } = useI18n();

  return (
    <>
      <section className="template-summary-bar" data-section="preset-prompts">
        <div className="template-summary-bar__header">
          <div className="template-summary-bar__title-group">
            <span className="template-panel__label">{t("template.bar.presetPrompts")}</span>
            {ctx.resolvedSelectedPresets.length > 0 ? (
              <span className="template-summary-pill">
                {t("template.bar.presetsSelectedCount", { count: ctx.resolvedSelectedPresets.length })}
              </span>
            ) : null}
          </div>
          <Button
            aria-label={t("template.bar.editPresetPrompts")}
            icon={<Pencil aria-hidden className="button__icon" />}
            onClick={() => ctx.setUserPromptDialogOpen(true)}
            variant="ghost"
          >
            {t("template.mode.edit")}
          </Button>
        </div>
        <div className="template-summary-bar__body">
          {ctx.resolvedSelectedPresets.length === 0 ? (
            <span className="template-summary-bar__empty">{t("template.bar.noPresets")}</span>
          ) : (
            <div className="template-summary-chips" role="list">
              {ctx.visiblePresetChips.map((preset) => (
                <span
                  className={`template-summary-chip${preset.isDeleted ? " is-unavailable" : ""}`}
                  key={preset.id}
                  role="listitem"
                  style={
                    {
                      "--template-character-color": preset.color || "#5b8def",
                    } as CSSProperties
                  }
                >
                  <span aria-hidden className="template-character-card__dot" />
                  <span className="template-summary-chip__name">{preset.name}</span>
                  {preset.isDeleted ? (
                    <span className="template-summary-chip__badge">{t("template.presets.deletedBadge")}</span>
                  ) : null}
                </span>
              ))}
              {ctx.hiddenPresetCount > 0 ? (
                <span className="template-summary-pill">
                  {t("template.bar.moreItems", { count: ctx.hiddenPresetCount })}
                </span>
              ) : null}
            </div>
          )}
        </div>
      </section>

      <UserPromptPresetsDialog
        appliedPresets={ctx.appliedPresetsSnapshot}
        baseScenario={ctx.baseScenario}
        library={ctx.presetsLibrary}
        libraryError={ctx.presetsLibraryError ? t("template.presets.loadFailed") : ""}
        libraryLoading={ctx.presetsLibraryPending}
        libraryReady={ctx.presetsLibraryReady}
        onClose={() => ctx.setUserPromptDialogOpen(false)}
        onConfirm={ctx.handleConfirmUserPrompt}
        onRetryLibrary={ctx.retryPresetsLibrary}
        onSaveLibrary={ctx.saveLibraryPresets}
        open={ctx.userPromptDialogOpen}
        savingLibrary={ctx.savePresetsPending}
        selectedPresetIds={ctx.draft.selectedPresetIds ?? []}
      />
    </>
  );
}
