import { SlidersHorizontal } from "lucide-react";

import { resolveFormGroupTitle } from "../../../shared/form-schema";
import { useI18n } from "../../../shared/i18n";
import { SchemaFieldGrid, type PageSectionProps } from "../../../shared/ui";
import { AdapterExtraForm } from "../AdapterExtraForm";
import { TtsBundleSection } from "../TtsBundleSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";
import { adapterSchema, hasAdapterSchema } from "../apiSettingsUtils";
import { useApiTtsController } from "../controllers/useApiTtsController";
import "./ApiTtsPanel.css";

export function ApiTtsPanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  const { t } = useI18n();
  const tts = useApiTtsController(ctx);
  const ttsGroup = ctx.apiSchema.find((group) => group.id === "tts");
  const ttsExtraSchema = adapterSchema(ctx.adapterCatalog?.tts, ctx.draft.tts_provider);
  const hasExtra = hasAdapterSchema(ttsExtraSchema);
  const normalizedProvider = ctx.draft.tts_provider.trim().toLowerCase();
  const activeTtsOption = (ctx.adapterCatalog?.tts ?? []).find(
    (option) => option.value.trim().toLowerCase() === normalizedProvider,
  );
  const ttsProviderLabel = activeTtsOption?.label || ctx.draft.tts_provider;

  return (
    <>
      <TtsBundleSection
        canCancelDownload={tts.canCancelDownload}
        cancelPending={tts.cancelPending}
        dialogOpen={tts.dialogOpen}
        downloadPending={tts.downloadPending}
        error={tts.error}
        id={id}
        kind={tts.kind}
        onCancelDownload={tts.onCancelDownload}
        onCloseDialog={tts.closeDialog}
        onKindChange={tts.onKindChange}
        onOpenDialog={tts.openTtsBundleDialog}
        onStartDownload={tts.onStartDownload}
        recommendation={tts.recommendation}
        recommendationError={tts.recommendationError}
        recommendationLoading={tts.recommendationLoading}
        savePending={ctx.savePending}
        task={tts.task}
      />
      {ttsGroup ? (
        <section className="section schema-section api-tts-panel">
          <div className="section__header">
            <h2 className="section__title">{resolveFormGroupTitle(ttsGroup, t)}</h2>
          </div>
          <SchemaFieldGrid
            disabled={ctx.savePending}
            errors={ctx.errors}
            group={ttsGroup}
            onChange={tts.updateTtsDraftFromSchema}
            value={ctx.draft}
          />
          {hasExtra ? (
            <details className="api-tts-panel__extra" key={ctx.draft.tts_provider}>
              <summary className="api-tts-panel__extra-summary">
                <SlidersHorizontal aria-hidden className="api-tts-panel__extra-icon" />
                <span>{t("ops.api.extra.providerTitle", { provider: ttsProviderLabel })}</span>
              </summary>
              <AdapterExtraForm
                disabled={ctx.savePending}
                onChange={(key, value) =>
                  ctx.updateAdapterExtra("tts_extra_configs", ctx.draft.tts_provider, key, value)
                }
                schema={ttsExtraSchema}
                values={ctx.draft.tts_extra_configs?.[ctx.draft.tts_provider] ?? {}}
              />
            </details>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
