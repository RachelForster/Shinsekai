import { PortraitCropDialog } from "../../../shared/components/PortraitCropDialog";
import { useI18n } from "../../../shared/i18n";
import { AlertDialog, type PageSectionProps } from "../../../shared/ui";
import { MediaAutoLabelProgressDialog } from "../../media-auto-label/MediaAutoLabelProgressDialog";
import { CharacterSpritesSection } from "../CharacterSpritesSection";
import { SmartOutfitGroupDialog } from "../SmartOutfitGroupDialog";
import { SpriteTagsDialog } from "../SpriteTagsDialog";
import type { CharacterPageContext } from "../characterContext";
import { useCharacterSpritesController } from "../controllers/useCharacterSpritesController";

export function CharacterSpritesPanel({ ctx, id }: PageSectionProps<CharacterPageContext>) {
  const { t } = useI18n();
  const sprites = useCharacterSpritesController(ctx);

  return (
    <>
      <CharacterSpritesSection
        activeSpriteGroup={sprites.activeSpriteGroup}
        autoLabelAvailable={ctx.visionAvailable}
        autoLabelDisabled={sprites.autoLabelDisabled}
        autoLabelPending={sprites.autoLabelPending}
        draft={ctx.draft}
        emotionTagsPending={sprites.emotionTagsPending}
        generateDisabled={sprites.generateDisabled}
        generateHint={sprites.generateHint}
        id={id}
        isSavedCharacter={ctx.isSavedCharacter}
        onActiveSpriteGroupChange={sprites.setActiveSpriteGroup}
        onApplySpriteGroups={sprites.handleApplySpriteGroups}
        onAutoLabel={sprites.handleAutoLabel}
        onClearSprites={sprites.requestClearSprites}
        onGenerate={ctx.openSpriteGeneration}
        onOpenBulkTags={sprites.openBulkSpriteTagsDialog}
        onOpenPortraitCrop={sprites.handleOpenPortraitCrop}
        onOpenSmartGroup={sprites.openSmartGroup}
        onPendingVoicePathChange={sprites.updatePendingVoicePath}
        onSaveTags={sprites.saveSpriteTags}
        onSelectSprite={sprites.setSelectedSpriteIndex}
        onSpriteDelete={sprites.requestSelectedSpriteDelete}
        onSpriteTagChange={(value) => sprites.updateSpriteTag(sprites.selectedSpriteIndex, value)}
        onSpriteUpload={sprites.uploadSprites}
        onSpriteVoiceDelete={sprites.requestSelectedSpriteVoiceDelete}
        onSpriteVoiceTextBlur={sprites.saveSelectedSpriteVoiceText}
        onSpriteVoiceTextChange={sprites.updateSelectedSpriteVoiceText}
        onSpriteVoiceUpload={sprites.uploadSelectedSpriteVoice}
        onSpriteVoiceTypeChange={sprites.handleSpriteVoiceTypeChange}
        pendingVoicePath={sprites.pendingVoicePath}
        selectedSprite={sprites.selectedSprite}
        selectedSpriteIndex={sprites.selectedSpriteIndex}
        selectedSpriteTag={sprites.selectedSpriteTag}
        spriteDeletePending={sprites.spriteDeletePending}
        spriteGalleryItems={sprites.spriteGalleryItems}
        spriteGroupsPending={sprites.spriteGroupsPending}
        spriteUploadPending={sprites.spriteUploadPending}
        voiceDeletePending={sprites.voiceDeletePending}
        voiceUploadPending={sprites.voiceUploadPending}
      />

      <SpriteTagsDialog
        draft={sprites.bulkSpriteTagsDraft}
        onChange={sprites.setBulkSpriteTagsDraft}
        onClose={sprites.closeBulkTags}
        onConfirm={sprites.confirmBulkSpriteTags}
        open={sprites.bulkSpriteTagsOpen}
      />

      <SmartOutfitGroupDialog
        characterName={ctx.currentCharacterName}
        onApplied={sprites.handleApplySmartGroup}
        onClose={sprites.closeSmartGroup}
        open={sprites.smartGroupOpen}
        sprites={ctx.draft.sprites}
      />

      <PortraitCropDialog
        character={ctx.draft}
        error={sprites.portraitCropError}
        initialSpriteIndex={sprites.selectedSpriteIndex}
        onClose={sprites.closePortraitCrop}
        onSave={sprites.handleSavePortraitCrop}
        open={sprites.portraitCropOpen}
        saving={sprites.portraitCropSaving}
      />

      <AlertDialog
        body={sprites.pendingDeleteCopy?.body ?? ""}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={sprites.pendingDeleteCopy?.confirmLabel ?? t("common.delete")}
        onCancel={sprites.cancelPendingDelete}
        onConfirm={sprites.confirmPendingDelete}
        open={sprites.pendingDeleteOpen}
        title={sprites.pendingDeleteCopy?.title ?? t("common.delete")}
      />

      <MediaAutoLabelProgressDialog
        onClose={sprites.closeAutoLabelDialog}
        open={sprites.autoLabelDialogOpen}
        pending={sprites.autoLabelPending}
        result={sprites.autoLabelData}
        task={sprites.autoLabelTask}
      />
    </>
  );
}
