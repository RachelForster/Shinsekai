import { useI18n } from "../../../shared/i18n";
import { AlertDialog, type PageSectionProps } from "../../../shared/ui";
import { MediaAutoLabelProgressDialog } from "../../media-auto-label/MediaAutoLabelProgressDialog";
import { BackgroundSpriteGallery } from "../BackgroundSpriteGallery";
import { BackgroundTagsDialog } from "../BackgroundTagsDialog";
import type { BackgroundPageContext } from "../backgroundContext";
import { useBackgroundImagesController } from "../controllers/useBackgroundImagesController";

export function BackgroundImagesSection({ ctx, id }: PageSectionProps<BackgroundPageContext>) {
  const { t } = useI18n();
  const images = useBackgroundImagesController(ctx);

  return (
    <>
      <BackgroundSpriteGallery
        autoLabelAvailable={ctx.visionAvailable}
        autoLabelDisabled={images.autoLabelDisabled}
        autoLabelPending={images.autoLabelPending}
        currentBackgroundName={ctx.currentBackgroundName}
        deletePending={images.deletePending}
        id={id}
        imageRowTags={images.imageRowTags}
        onAutoLabel={images.handleAutoLabel}
        onClearImages={images.requestClearImages}
        onDeleteImage={images.handleImageDelete}
        onOpenBulkTags={images.openBulkImageTagsDialog}
        onSaveImageTags={images.handleSaveImageTags}
        onSelectImage={images.setSelectedImageIndex}
        onUpdateImageTag={images.updateImageRowTag}
        onUploadImages={images.uploadImages}
        saveTagsPending={images.saveTagsPending}
        selectedImageIndex={images.selectedImageIndex}
        sprites={ctx.currentDraft.sprites}
        uploadPending={images.uploadPending}
      />

      <BackgroundTagsDialog
        draft={images.bulkImageTagsDraft}
        fieldLabel={t("background.field.bgTags")}
        help={t("background.asset.batchImageTagsHelp")}
        onChange={images.setBulkImageTagsDraft}
        onClose={images.closeBulkImageTags}
        onConfirm={images.confirmBulkImageTags}
        open={images.bulkImageTagsOpen}
        title={t("background.asset.batchImageTagsTitle")}
      />

      <AlertDialog
        body={images.pendingDeleteCopy?.body ?? ""}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={images.pendingDeleteCopy?.confirmLabel ?? t("common.delete")}
        onCancel={images.cancelPendingDelete}
        onConfirm={images.confirmPendingDelete}
        open={images.pendingDeleteOpen}
        title={images.pendingDeleteCopy?.title ?? t("common.delete")}
      />

      <MediaAutoLabelProgressDialog
        onClose={images.closeAutoLabelDialog}
        open={images.autoLabelDialogOpen}
        pending={images.autoLabelPending}
        result={images.autoLabelData}
        task={images.autoLabelTask}
      />
    </>
  );
}
