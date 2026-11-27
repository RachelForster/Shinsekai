import { lazy, Suspense } from "react";

import { useI18n } from "../../../shared/i18n";
import { AlertDialog } from "../../../shared/ui";
import { RuntimeModeDialog } from "../../runtime-mode/RuntimeModeDialog";
import { CHAT_IMAGE_EXTENSIONS } from "../attachments";
import type { ChatStagePageController } from "../controllers/useChatStagePageController";

const CurrentConversationEditorDialog = lazy(() =>
  import("../../chat-workspace/CurrentConversationEditorDialog").then((module) => ({
    default: module.CurrentConversationEditorDialog,
  })),
);

export interface ChatStageRootOverlaysProps {
  controller: ChatStagePageController;
}

export function ChatStageRootOverlays({ controller }: ChatStageRootOverlaysProps) {
  const { t } = useI18n();
  const { commands, historyReplay, interaction, modals } = controller;

  return (
    <>
      <input
        accept={CHAT_IMAGE_EXTENSIONS.join(",")}
        aria-label={t("chat.input.imagePickerTitle")}
        hidden
        multiple
        onChange={(event) => interaction.handlePickedFiles(event.currentTarget)}
        ref={interaction.imageAttachmentInputRef}
        type="file"
      />
      <input
        aria-label={t("chat.input.filePickerTitle")}
        hidden
        multiple
        onChange={(event) => interaction.handlePickedFiles(event.currentTarget)}
        ref={interaction.fileAttachmentInputRef}
        type="file"
      />
      {modals.conversationEditorOpen && (
        <Suspense fallback={null}>
          <CurrentConversationEditorDialog
            onClose={() => modals.setConversationEditorOpen(false)}
            onApplied={(snapshot) => {
              interaction.replaceSession(snapshot);
              interaction.showDialogImmediately();
              modals.setConversationEditorOpen(false);
            }}
          />
        </Suspense>
      )}
      <AlertDialog
        body={t("chat.clear.confirmBody")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("chat.clear.confirmAction")}
        onCancel={() => modals.setConfirmClearHistory(false)}
        onConfirm={() => void commands.sendCommand({ type: "clear-history" })}
        open={modals.confirmClearHistory}
        title={t("chat.clear.confirmTitle")}
      />
      <AlertDialog
        body={t("chat.history.revertConfirmBody")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("chat.history.revertConfirmAction")}
        onCancel={() => historyReplay.setConfirmRevertUserIndex(null)}
        onConfirm={historyReplay.confirmRevertHistory}
        open={historyReplay.confirmRevertUserIndex != null}
        title={t("chat.history.revertConfirmTitle")}
      />
      {modals.runtimeModeOpen ? (
        <RuntimeModeDialog onClose={() => modals.setRuntimeModeOpen(false)} open={modals.runtimeModeOpen} />
      ) : null}
    </>
  );
}
