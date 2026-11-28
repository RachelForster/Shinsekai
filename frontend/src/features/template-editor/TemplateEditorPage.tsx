import { useMemo } from "react";

import { useI18n } from "../../shared/i18n";
import { usePluginPageSectionDescriptors } from "../../shared/plugin/PluginPageSections";
import { PageSectionHost } from "../../shared/ui";
import { ChatInitializationDialog } from "../chat-startup/ChatInitializationDialog";
import { MobileAccessDialog } from "../mobile-access/MobileAccessDialog";
import { PrimaryCharacterDialog } from "./PrimaryCharacterDialog";
import { TemplatePageFooter } from "./TemplatePageFooter";
import { TemplatePageHeader } from "./TemplatePageHeader";
import { useTemplateEditorController, type TemplateEditorPageProps } from "./controllers/useTemplateEditorController";
import type { TemplateEditorContext, TemplateSectionSlot } from "./templateContext";
import { TEMPLATE_EDITOR_SECTIONS } from "./templateSections";
import "./TemplateEditorPage.css";

export function TemplateEditorPage(props: TemplateEditorPageProps) {
  const { t } = useI18n();
  const ctx = useTemplateEditorController(props);
  const entityId = ctx.templateSelectValue || ctx.draft.id || undefined;
  const pluginSections = usePluginPageSectionDescriptors<TemplateEditorContext, TemplateSectionSlot>(
    { entityId, entityType: "template", page: "template" },
    {
      context: { entityId, entityType: "template", page: "template" },
      defaultSlot: "main",
      orderBase: 1000,
      preserveDeclaredSlot: true,
    },
  );
  const allSections = useMemo(() => [...TEMPLATE_EDITOR_SECTIONS, ...pluginSections], [pluginSections]);

  return (
    <div className="page template-page">
      <TemplatePageHeader ctx={ctx} />

      <div className="template-workbench">
        <section className="template-workbench__main">
          <PageSectionHost ctx={ctx} sections={allSections} slot="main" />
        </section>

        <aside className="template-options-panel">
          <div className="template-options-panel__header">
            <h2 className="template-options-panel__title">{t("template.section.stageRuntime")}</h2>
          </div>
          <PageSectionHost ctx={ctx} sections={allSections} slot="sidebar" />
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
