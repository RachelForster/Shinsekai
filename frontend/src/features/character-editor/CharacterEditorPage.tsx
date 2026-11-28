import { useMemo } from "react";

import { useI18n } from "../../shared/i18n";
import { usePluginPageSectionDescriptors } from "../../shared/plugin/PluginPageSections";
import { AlertDialog, PageSectionHost, PageSectionNav, useVisibleSectionNavItems } from "../../shared/ui";
import { CharacterPageHeader } from "./CharacterPageHeader";
import { CharacterRenameTextDialog } from "./CharacterRenameTextDialog";
import type { CharacterPageContext, CharacterSectionSlot } from "./characterContext";
import { CHARACTER_EDITOR_SECTIONS } from "./characterSections";
import { SpriteGenerationPage } from "./SpriteGenerationPage";
import { useCharacterPageController } from "./controllers/useCharacterPageController";
import "./CharacterEditorPage.css";

export { mergeSprites } from "./characterContext";

export function CharacterEditorPage() {
  const { t } = useI18n();
  const ctx = useCharacterPageController();
  const entityId = ctx.isCreating ? undefined : ctx.currentCharacterName || undefined;
  const pluginSections = usePluginPageSectionDescriptors<CharacterPageContext, CharacterSectionSlot>(
    { entityId, entityType: "character", page: "character" },
    { context: { entityId, entityType: "character", page: "character" }, defaultSlot: "body", orderBase: 1000 },
  );
  const allSections = useMemo(() => [...CHARACTER_EDITOR_SECTIONS, ...pluginSections], [pluginSections]);
  const navItems = useVisibleSectionNavItems(allSections, ctx);

  if (ctx.spriteGenerationOpen) {
    return (
      <SpriteGenerationPage
        character={ctx.draft}
        name={ctx.currentCharacterName}
        onClose={ctx.closeSpriteGeneration}
        onImported={ctx.handleSpriteGenerationImported}
      />
    );
  }

  return (
    <div className="page character-page">
      <CharacterPageHeader
        autoSaveError={ctx.autoSaveError}
        autoSavePhase={ctx.autoSavePhase}
        canCancelCreate={ctx.isCreating && ctx.data.length > 0}
        characters={ctx.data}
        exportPending={ctx.exportPending}
        importPending={ctx.importPending}
        isCreating={ctx.isCreating}
        isLoading={ctx.isLoading}
        onCancelCreate={ctx.cancelCreatingCharacter}
        onCreate={ctx.startCreatingCharacter}
        onExport={ctx.exportCurrentCharacter}
        onImport={ctx.importCharacters}
        onRetryAutoSave={ctx.autoSaveRetry}
        onSave={ctx.saveDraft}
        onSelectCharacter={ctx.selectExistingCharacter}
        pendingIdentity={ctx.nameDirty || ctx.spritePrefixDirty}
        savePending={ctx.savePending}
        sectionNav={<PageSectionNav ariaLabel={t("character.title")} items={navItems} />}
        selectedName={ctx.selectedName}
      />

      <div className="settings-grid character-page__content">
        <div className="character-page__top-grid">
          <PageSectionHost ctx={ctx} sections={allSections} slot="top-grid" />
        </div>
        <PageSectionHost ctx={ctx} sections={allSections} slot="body" />
      </div>

      <AlertDialog
        body={t("character.delete.confirmBody", { name: ctx.pendingDelete ?? "" })}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("common.delete")}
        onCancel={ctx.cancelDeleteCharacter}
        onConfirm={ctx.confirmDeleteCharacter}
        open={Boolean(ctx.pendingDelete)}
        title={t("character.delete.confirmTitle")}
      />

      <CharacterRenameTextDialog
        onCancel={ctx.cancelPendingRenameText}
        onKeepOriginalText={ctx.confirmRenameKeepText}
        onReplaceText={ctx.confirmRenameReplaceText}
        pending={ctx.identityPending}
        preview={ctx.pendingRenameText}
      />
    </div>
  );
}
