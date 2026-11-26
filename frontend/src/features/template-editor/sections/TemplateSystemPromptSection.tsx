import { Pencil } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { Button, type PageSectionProps } from "../../../shared/ui";
import { resolveDialogFormatLabel, SystemPromptDialog } from "../SystemPromptDialog";
import type { TemplateEditorContext } from "../templateContext";

export function TemplateSystemPromptSection({ ctx }: PageSectionProps<TemplateEditorContext>) {
  const { t } = useI18n();

  return (
    <>
      <section className="template-summary-bar" data-section="system-prompt">
        <div className="template-summary-bar__header">
          <div className="template-summary-bar__title-group">
            <span className="template-panel__label">{t("template.bar.systemPrompt")}</span>
            <span className={`template-status-pill ${ctx.systemStatusPill.className}`}>
              {ctx.systemStatusPill.label}
            </span>
          </div>
          <Button
            aria-label={t("template.bar.editSystemPrompt")}
            icon={<Pencil aria-hidden className="button__icon" />}
            onClick={() => ctx.setSystemPromptDialogOpen(true)}
            variant="ghost"
          >
            {t("template.mode.edit")}
          </Button>
        </div>
        <div className="template-summary-bar__body">
          <div className="template-summary-chips">
            <span className="template-summary-pill">
              {t("template.bar.outputFormat", {
                format: resolveDialogFormatLabel(ctx.outputFormat, ctx.dialogFormats, t),
              })}
            </span>
            <span className="template-summary-pill">
              {t(ctx.mediaSelectionMode === "semantic" ? "template.semanticMedia.label" : "template.bar.mediaIndexed")}
            </span>
            <span className="template-summary-pill">
              {t("template.bar.rulesEnabledCount", { count: ctx.enabledRulesCount })}
            </span>
          </div>
        </div>
      </section>

      <SystemPromptDialog
        canAutoSync={
          ctx.selectedCharacters.length > 0 && (ctx.selectedCharacters.length <= 4 || Boolean(ctx.characterPromptMode))
        }
        dialogFormats={ctx.dialogFormats}
        generating={ctx.generatePending}
        onClose={() => ctx.setSystemPromptDialogOpen(false)}
        onConfirm={ctx.handleConfirmSystemPrompt}
        onRegenerate={ctx.handleRegenerateFromDialog}
        open={ctx.systemPromptDialogOpen}
        rules={{
          maxDialogItems: ctx.maxDialogItems,
          maxSpeechChars: ctx.maxSpeechChars,
          mediaSelectionMode: ctx.mediaSelectionMode,
          outputFormat: ctx.outputFormat,
          useChoice: ctx.useChoice,
          useCot: ctx.useCot,
          useEffectPrompt: ctx.useEffectPrompt,
          useNarration: ctx.useNarration,
          useStat: ctx.useStat,
          useTranslation: ctx.useTranslation,
        }}
        systemConfigStale={ctx.systemConfigStale}
        systemManuallyEdited={ctx.systemManuallyEdited}
        systemText={ctx.draft.system ?? ""}
      />
    </>
  );
}
