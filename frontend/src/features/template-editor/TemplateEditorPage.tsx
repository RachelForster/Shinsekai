import { useI18n } from "../../shared/i18n";
import { PageSectionHost } from "../../shared/ui";
import { ChatInitializationDialog } from "../chat-startup/ChatInitializationDialog";
import { MobileAccessDialog } from "../mobile-access/MobileAccessDialog";
import { PrimaryCharacterDialog } from "./PrimaryCharacterDialog";
import { TemplatePageFooter } from "./TemplatePageFooter";
import { TemplatePageHeader } from "./TemplatePageHeader";
import { useTemplateEditorController, type TemplateEditorPageProps } from "./controllers/useTemplateEditorController";
import { TEMPLATE_EDITOR_SECTIONS } from "./templateSections";
import "./TemplateEditorPage.css";

export function TemplateEditorPage(props: TemplateEditorPageProps) {
  const { t } = useI18n();
  const ctx = useTemplateEditorController(props);

  return (
    <div className="page template-page">
      <TemplatePageHeader ctx={ctx} />

      <div className="template-workbench">
        <section className="template-workbench__main">
          <PageSectionHost ctx={ctx} sections={TEMPLATE_EDITOR_SECTIONS} slot="main" />
        </section>

        <aside className="template-options-panel">
          <div className="template-options-panel__header">
            <h2 className="template-options-panel__title">{t("template.section.stageRuntime")}</h2>
          </div>
          <PageSectionHost ctx={ctx} sections={TEMPLATE_EDITOR_SECTIONS} slot="sidebar" />
        </aside>
      </div>

      <TemplatePageFooter ctx={ctx} />

      <PrimaryCharacterDialog
        characters={ctx.selectedCharacterRecords.filter((character) => character.name !== ctx.effectivePlayerCharacter)}
        initialPrimaryCharacters={ctx.primaryCharacters}
        onConfirm={(names) => void ctx.confirmPrimaryCharacters(names)}
        onUseAll={ctx.useAllCharactersAsPrimary}
        open={ctx.primaryCharacterDialogOpen}
        pending={ctx.ensureBriefsPending}
      />
      <ChatInitializationDialog
        error={ctx.initializationError}
        onClose={ctx.closeInitialization}
        open={!ctx.initializationServiceProvided && ctx.initializationOpen}
        pending={ctx.initializationPending}
        task={ctx.initializationTask}
      />
      <MobileAccessDialog
        info={ctx.mobileAccessInfo}
        onClose={ctx.closeMobileAccess}
        onOpenLocalChat={ctx.openLocalChatFromMobile}
      />
    </div>
  );
}
