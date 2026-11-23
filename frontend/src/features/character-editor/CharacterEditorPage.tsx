import { useI18n } from "../../shared/i18n";
import { AlertDialog, PageSectionHost, PageSectionNav, useVisibleSectionNavItems } from "../../shared/ui";
import { CharacterPageHeader } from "./CharacterPageHeader";
import { CHARACTER_EDITOR_SECTIONS } from "./characterSections";
import { SpriteGenerationPage } from "./SpriteGenerationPage";
import { useCharacterPageController } from "./controllers/useCharacterPageController";
import "./CharacterEditorPage.css";

export { mergeSprites } from "./characterContext";

export function CharacterEditorPage() {
  const { t } = useI18n();
  const ctx = useCharacterPageController();
  const navItems = useVisibleSectionNavItems(CHARACTER_EDITOR_SECTIONS, ctx);

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
          <PageSectionHost ctx={ctx} sections={CHARACTER_EDITOR_SECTIONS} slot="top-grid" />
        </div>
        <PageSectionHost ctx={ctx} sections={CHARACTER_EDITOR_SECTIONS} slot="body" />
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
    </div>
  );
}
