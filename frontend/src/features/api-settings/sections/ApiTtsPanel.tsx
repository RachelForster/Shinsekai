import { SchemaDrivenForm, type PageSectionProps } from "../../../shared/ui";
import { TtsBundleSection } from "../TtsBundleSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";
import { useApiTtsController } from "../controllers/useApiTtsController";

export function ApiTtsPanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  const tts = useApiTtsController(ctx);

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
      <SchemaDrivenForm
        disabled={ctx.savePending}
        errors={ctx.errors}
        groups={ctx.apiSchema.filter((g) => g.id === "tts")}
        onChange={tts.updateTtsDraftFromSchema}
        value={ctx.draft}
      />
    </>
  );
}
