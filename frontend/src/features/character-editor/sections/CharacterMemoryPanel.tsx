import { useI18n } from "../../../shared/i18n";
import { AlertDialog, type PageSectionProps } from "../../../shared/ui";
import { CharacterMemoryDialogs } from "../CharacterMemoryDialogs";
import { CharacterMemoryImportDialogs } from "../CharacterMemoryImportDialogs";
import { CharacterMemorySection } from "../CharacterMemorySection";
import type { CharacterPageContext } from "../characterContext";
import { useCharacterMemorySectionController } from "../controllers/useCharacterMemorySectionController";

export function CharacterMemoryPanel({ ctx, id }: PageSectionProps<CharacterPageContext>) {
  const { t } = useI18n();
  const memory = useCharacterMemorySectionController(ctx);
  const { memoryController, memoryImportController, memoryName } = memory;

  return (
    <>
      <CharacterMemorySection
        activeSearchQuery={memoryController.activeSearchQuery}
        addAsCanon={memoryController.addAsCanon}
        addPending={memoryController.addPending}
        awakenPending={memoryController.awakenPending}
        data={memoryController.data}
        deletePending={memoryController.deletePending}
        depError={memoryController.depError}
        depInstalling={memoryController.depInstalling}
        error={memoryController.error}
        id={id}
        isChecking={memoryController.isChecking}
        isError={memoryController.isError}
        isFetched={memoryController.isFetched}
        isFetching={memoryController.isFetching}
        isLoading={memoryController.isLoading}
        memoryImportPending={memoryImportController.previewPending || memoryImportController.importPending}
        memoryInput={memoryController.memoryInput}
        memoryName={memoryName}
        memoryPage={memoryController.memoryPage}
        memoryTotalPages={memoryController.memoryTotalPages}
        onAddAsCanonChange={memoryController.setAddAsCanon}
        onAddMemory={() => void memoryController.add()}
        onAwakenMemory={(item) => void memoryController.awakenMemory({ memoryId: item.id, name: memoryName })}
        onClearSearch={memoryController.clearSearch}
        onDeleteMemory={memory.requestMemoryDelete}
        onImportMemories={() => void memoryImportController.openPicker()}
        onInstallDep={() => void memoryController.installDependency()}
        onMemoryInputChange={memoryController.setMemoryInput}
        onMemoryPageChange={memoryController.setMemoryPage}
        onPinMemory={(item, pinned) => void memoryController.pinMemory({ memoryId: item.id, name: memoryName, pinned })}
        onRefresh={() => void memoryController.refresh()}
        onSearch={() => void memoryController.search()}
        onSearchInputChange={memoryController.setSearchInput}
        pinPending={memoryController.pinPending}
        searchInput={memoryController.searchInput}
        searchPending={memoryController.searchPending}
      />

      <AlertDialog
        body={memory.pendingDeleteBody}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("common.delete")}
        onCancel={memory.cancelMemoryDelete}
        onConfirm={() => void memory.confirmMemoryDelete()}
        open={memory.pendingDeleteOpen}
        title={t("character.memory.delete")}
      />

      <CharacterMemoryDialogs
        depInstalling={memoryController.depInstalling}
        dependencyOpen={memoryController.dependencyDialogOpen}
        dependencyTask={memoryController.dependencyTask}
        loadingMessage={memoryController.loadingMessage}
        loadingOpen={memoryController.loadingDialogOpen}
        loadingTask={memoryController.loadingTask}
        onCloseDependency={memoryController.closeDependencyDialog}
        onCloseLoading={memoryController.closeLoadingDialog}
      />

      <CharacterMemoryImportDialogs
        importPending={memoryImportController.importPending}
        onClosePicker={memoryImportController.closePicker}
        onClosePreview={memoryImportController.closePreview}
        onCloseTask={memoryImportController.closeTask}
        onConfirm={() => void memoryImportController.confirmImport()}
        onSelect={(items) => void memoryImportController.previewItems(items)}
        pickerOpen={memoryImportController.pickerOpen}
        preview={memoryImportController.preview}
        previewOpen={memoryImportController.previewOpen}
        result={memoryImportController.result}
        task={memoryImportController.task}
        taskOpen={memoryImportController.taskOpen}
      />
    </>
  );
}
