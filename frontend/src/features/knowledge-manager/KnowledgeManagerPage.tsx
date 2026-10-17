import { RefreshCw } from "lucide-react";
import { AsyncButton, PageSectionNav } from "../../shared/ui";
import { useI18n } from "../../shared/i18n";
import { KnowledgeInstancePicker } from "./KnowledgeInstancePicker";
import { KnowledgeBrowser } from "./KnowledgeBrowser";
import { KnowledgeImportPicker } from "./KnowledgeImportPicker";
import { useKnowledgeController } from "./useKnowledgeController";
import { useKnowledgeImportController } from "./useKnowledgeImportController";
import { type ReactNode } from "react";
import { KnowledgeImportDialogs, KnowledgeLoadingDialog } from "./KnowledgeDialogs";
import "./KnowledgeManagerPage.css";

export function KnowledgeManagerPage({ embedded = false }: { embedded?: boolean }) {
  const { t } = useI18n();
  const controller = useKnowledgeController();
  const importer = useKnowledgeImportController({
    ensureReady: controller.ensureKnowledgeModelReady,
    onSettled: controller.importSettled,
  });

  return (
    <div className={embedded ? "knowledge-page knowledge-page--embedded" : "page knowledge-page"}>
      <KnowledgePageHeader
        embedded={embedded}
        sectionNav={
          <PageSectionNav
            ariaLabel={t("knowledge.views")}
            items={[
              { id: "knowledge-entries", label: t("knowledge.information") },
              { id: "knowledge-characters", label: t("knowledge.boundCharacters") },
            ]}
          />
        }
        controller={controller}
        disabled={importer.importPending}
        actions={
          <>
            <KnowledgeImportPicker
              importPending={importer.previewPending || importer.importPending || controller.refreshPending}
              importKnowledgeId={importer.importKnowledgeId}
              selectedKnowledge={controller.selectedKnowledge}
              onImportKnowledgeIdChange={importer.setImportKnowledgeId}
              onImportFiles={importer.previewFiles}
            />
            <AsyncButton
              icon={<RefreshCw aria-hidden className="button__icon" />}
              disabled={
                importer.previewPending ||
                importer.importPending ||
                controller.writePending ||
                controller.bindingPending
              }
              loading={controller.refreshPending}
              onClick={controller.refresh}
            >
              {t("knowledge.refresh")}
            </AsyncButton>
          </>
        }
      />
      {embedded ? (
        <div className="knowledge-section__search">
          <KnowledgeInstancePicker controller={controller} disabled={importer.importPending} />
        </div>
      ) : null}
      <KnowledgeBrowser controller={controller} disabled={importer.importPending} embedded={embedded} />
      <KnowledgeLoadingDialog
        open={controller.modelLoadingOpen}
        message={controller.modelLoadingMessage}
        task={controller.modelLoadingTask}
        onClose={controller.closeLoadingDialog}
      />
      <KnowledgeImportDialogs
        knowledgeId={importer.previewOpen ? importer.importKnowledgeId.trim() : importer.taskKnowledgeId}
        importPending={importer.importPending}
        onClosePreview={() => importer.setPreviewOpen(false)}
        onCloseTask={() => importer.setTaskOpen(false)}
        onConfirm={() => void importer.confirmImport()}
        preview={importer.preview}
        previewOpen={importer.previewOpen}
        result={importer.result}
        task={importer.task}
        taskOpen={importer.taskOpen}
      />
    </div>
  );
}

function KnowledgePageHeader({
  controller: c,
  disabled = false,
  actions,
  sectionNav,
  embedded = false,
}: {
  controller: ReturnType<typeof useKnowledgeController>;
  disabled?: boolean;
  actions?: ReactNode;
  sectionNav?: ReactNode;
  embedded?: boolean;
}) {
  const { t } = useI18n();
  if (embedded) {
    return (
      <div className="section__header">
        <h2 className="section__title">{t("knowledge.title")}</h2>
        <div className="page__actions">{actions}</div>
      </div>
    );
  }
  return (
    <header className="page__header knowledge-page__header">
      <div className="knowledge-page__heading">
        <h1 className="page__title">{t("knowledge.title")}</h1>
      </div>
      <div className="knowledge-page__toolbar">
        <KnowledgeInstancePicker controller={c} disabled={disabled} />
        <div className="page__actions knowledge-page__actions">{actions}</div>
      </div>
      {sectionNav}
    </header>
  );
}
