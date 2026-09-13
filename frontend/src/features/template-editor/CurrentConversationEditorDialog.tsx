import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { conversationsQueryKey, getCurrentConversation } from "../../entities/chat/repository";
import { ConversationTypeBadge } from "../../entities/chat/ConversationTypeBadge";
import { useI18n } from "../../shared/i18n";
import type { ChatSnapshot } from "../../shared/platform/types";
import { Button, Dialog } from "../../shared/ui";
import { TemplateEditorPage } from "./TemplateEditorPage";
import "./CurrentConversationEditorDialog.css";

export function CurrentConversationEditorDialog({
  onClose,
  onApplied,
}: {
  onClose: () => void;
  onApplied: (snapshot: ChatSnapshot) => void;
}) {
  const { t } = useI18n();
  const [pending, setPending] = useState(false);
  const current = useQuery({
    queryKey: [...conversationsQueryKey, "current"],
    queryFn: getCurrentConversation,
    staleTime: 0,
    gcTime: 0,
  });
  return (
    <Dialog
      open
      title={t("conversation.editCurrent")}
      closeLabel={t("common.close")}
      className="conversation-editor-dialog"
      dismissible={!pending}
      onClose={() => {
        if (!pending) onClose();
      }}
    >
      {current.isPending && <p role="status">{t("common.loading")}</p>}
      {current.isError && (
        <>
          <p role="alert">{current.error.message}</p>
          <Button onClick={() => void current.refetch()}>{t("common.refresh")}</Button>
        </>
      )}
      {current.isSuccess && !current.data && <p role="status">{t("conversation.unavailable")}</p>}
      {current.data && (
        <>
          <div className="conversation-editor-dialog__summary">
            <ConversationTypeBadge kind={current.data.kind} />
            <strong>{current.data.title || t("conversation.untitled")}</strong>
          </div>
          <p className="section__description">{t("conversation.applyHint")}</p>
          <TemplateEditorPage
            key={current.data.id}
            conversationId={current.data.id}
            onPendingChange={setPending}
            onApplied={onApplied}
          />
        </>
      )}
    </Dialog>
  );
}
