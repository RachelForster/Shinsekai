import { useI18n } from "../../../shared/i18n";
import { Button, Dialog, SchemaDrivenForm, type PageSectionProps } from "../../../shared/ui";
import { LlmConnectionSection } from "../LlmConnectionSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";
import { useApiLlmController } from "../controllers/useApiLlmController";

export function ApiLlmPanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  const { t } = useI18n();
  const llm = useApiLlmController(ctx);

  return (
    <>
      <LlmConnectionSection
        activeApiKey={llm.activeApiKey}
        activeModel={llm.activeModel}
        availableModelOptions={llm.availableModelOptions}
        connectionOk={llm.connectionOk}
        connectionTestPending={llm.connectionTestPending}
        disabled={ctx.savePending}
        draft={ctx.draft}
        fetchModelsPending={llm.fetchModelsPending}
        id={id}
        llmExtraSchema={llm.llmExtraSchema}
        llmProviderSelectOptions={llm.llmProviderSelectOptions}
        modelCandidateListId={llm.modelCandidateListId}
        modelUnsupportedThinking={llm.modelUnsupportedThinking}
        onAdapterExtraChange={(key, value) =>
          ctx.updateAdapterExtra("llm_extra_configs", ctx.draft.llm_provider, key, value)
        }
        onDraftPatch={llm.updateDraftAndResetModelFetch}
        onFetchModels={llm.handleFetchModels}
        onProviderChange={llm.updateProvider}
        onProviderMapChange={llm.updateProviderMap}
        onTestConnection={llm.handleTestLlmConnection}
        selectedOption={llm.selectedOption}
      />
      <SchemaDrivenForm
        collapsedGroupIds={["llm"]}
        disabled={ctx.savePending}
        errors={ctx.errors}
        groups={ctx.apiSchema.filter((g) => g.id === "llm")}
        onChange={ctx.updateDraftSynced}
        value={ctx.draft}
      />
      <Dialog
        closeLabel={t("common.close")}
        footer={
          <Button onClick={llm.closeConnectionDialog} variant="primary">
            {t("common.close")}
          </Button>
        }
        onClose={llm.closeConnectionDialog}
        open={llm.llmConnectionDialog !== null}
        title={t("api.llm.testTitle")}
      >
        <div className="api-page__llm-test-dialog-body" data-kind={llm.llmConnectionDialog?.kind ?? "error"}>
          {llm.llmConnectionDialog?.message ?? ""}
        </div>
      </Dialog>
    </>
  );
}
