import { useI18n } from "../../../shared/i18n";
import { AlertDialog, type PageSectionProps } from "../../../shared/ui";
import { BackgroundMusicSection } from "../BackgroundMusicSection";
import { BackgroundTagsDialog } from "../BackgroundTagsDialog";
import type { BackgroundPageContext } from "../backgroundContext";
import { useBackgroundBgmController } from "../controllers/useBackgroundBgmController";

export function BackgroundBgmSection({ ctx, id }: PageSectionProps<BackgroundPageContext>) {
  const { t } = useI18n();
  const bgm = useBackgroundBgmController(ctx);

  return (
    <>
      <BackgroundMusicSection
        batchDeletePending={bgm.batchDeletePending}
        bgmList={ctx.currentDraft.bgm_list}
        bgmRowTags={bgm.bgmRowTags}
        currentBackgroundName={ctx.currentBackgroundName}
        deletePending={bgm.deletePending}
        id={id}
        onBatchDelete={bgm.requestBatchDelete}
        onClearAll={bgm.requestClearAll}
        onDelete={bgm.handleBgmDelete}
        onOpenBulkTags={bgm.openBulkBgmTagsDialog}
        onSortToggle={bgm.toggleBgmSort}
        onTagChange={bgm.updateBgmRowTag}
        onToggleAllSelection={bgm.toggleAllBgmSelection}
        onToggleSelection={bgm.toggleBgmSelection}
        onUpload={bgm.uploadBgm}
        selectedBgmIndexSet={bgm.selectedBgmIndexSet}
        sortDirection={bgm.sortDirection}
        sortKey={bgm.sortKey}
        sortedBgmItems={bgm.sortedBgmItems}
        uploadPending={bgm.uploadPending}
      />

      <BackgroundTagsDialog
        draft={bgm.bulkBgmTagsDraft}
        fieldLabel={t("background.field.bgmTags")}
        help={t("background.asset.batchBgmTagsHelp")}
        onChange={bgm.setBulkBgmTagsDraft}
        onClose={bgm.closeBulkBgmTags}
        onConfirm={bgm.confirmBulkBgmTags}
        open={bgm.bulkBgmTagsOpen}
        title={t("background.asset.batchBgmTagsTitle")}
      />

      <AlertDialog
        body={bgm.pendingDeleteCopy?.body ?? ""}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={bgm.pendingDeleteCopy?.confirmLabel ?? t("common.delete")}
        onCancel={bgm.cancelPendingDelete}
        onConfirm={bgm.confirmPendingDelete}
        open={bgm.pendingDeleteOpen}
        title={bgm.pendingDeleteCopy?.title ?? t("common.delete")}
      />
    </>
  );
}
