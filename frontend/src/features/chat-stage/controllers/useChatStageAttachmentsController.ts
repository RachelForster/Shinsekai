import { useCallback, useRef, useState, type Dispatch } from "react";

import { uploadChatAttachments } from "../../../entities/chat/repository";
import type { MessageKey } from "../../../shared/i18n";
import type { ChatAttachmentInput } from "../../../shared/platform/types";
import type { ToastPayload } from "../../../shared/ui";
import { CHAT_ATTACHMENT_LIMIT, mergeChatAttachmentInputs } from "../attachments";
import type { ChatStageAction } from "../chatState";

export interface UseChatStageAttachmentsControllerOptions {
  dispatch: Dispatch<ChatStageAction>;
  inputAttachments: ChatAttachmentInput[];
  showToast: (options: ToastPayload) => void;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
}

export function useChatStageAttachmentsController({
  dispatch,
  inputAttachments,
  showToast,
  t,
}: UseChatStageAttachmentsControllerOptions) {
  const [attachmentUploadPending, setAttachmentUploadPending] = useState(false);
  const imageAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const fileAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const pendingAttachmentSlotsRef = useRef(0);

  const hasPendingUploads = useCallback(() => pendingAttachmentSlotsRef.current > 0, []);

  const addAttachments = (attachments: ChatAttachmentInput[]) => {
    const next = mergeChatAttachmentInputs(inputAttachments, attachments);
    const existing = new Set(inputAttachments.map((attachment) => `${attachment.kind}\0${attachment.path}`));
    const requested = new Set(
      attachments
        .map((attachment) => `${attachment.kind}\0${attachment.path.trim()}`)
        .filter((key) => !key.endsWith("\0"))
        .filter((key) => !existing.has(key)),
    );
    if (next.length - inputAttachments.length < requested.size) {
      showToast({
        kind: "error",
        message: t("chat.input.attachmentLimit", { count: CHAT_ATTACHMENT_LIMIT }),
        title: t("common.operationFailed"),
      });
    }
    dispatch({ attachments, type: "addAttachments" });
  };

  const handleDropFiles = async (files: File[]) => {
    if (!files.length) {
      return;
    }
    const availableSlots = Math.max(
      0,
      CHAT_ATTACHMENT_LIMIT - inputAttachments.length - pendingAttachmentSlotsRef.current,
    );
    const acceptedFiles = files.slice(0, availableSlots);
    if (acceptedFiles.length < files.length) {
      showToast({
        kind: "error",
        message: t("chat.input.attachmentLimit", { count: CHAT_ATTACHMENT_LIMIT }),
        title: t("common.operationFailed"),
      });
    }
    if (!acceptedFiles.length) {
      return;
    }
    pendingAttachmentSlotsRef.current += acceptedFiles.length;
    setAttachmentUploadPending(true);
    try {
      const { attachments } = await uploadChatAttachments(acceptedFiles);
      addAttachments(attachments);
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
        title: t("common.operationFailed"),
      });
    } finally {
      pendingAttachmentSlotsRef.current = Math.max(0, pendingAttachmentSlotsRef.current - acceptedFiles.length);
      setAttachmentUploadPending(pendingAttachmentSlotsRef.current > 0);
    }
  };

  const pickAttachments = (kind: ChatAttachmentInput["kind"]) => {
    (kind === "image" ? imageAttachmentInputRef.current : fileAttachmentInputRef.current)?.click();
  };

  const handlePickedFiles = (input: HTMLInputElement) => {
    const files = Array.from(input.files ?? []);
    input.value = "";
    void handleDropFiles(files);
  };

  const removeAttachment = useCallback(
    (attachment: ChatAttachmentInput) => {
      dispatch({
        attachments: inputAttachments.filter(
          (candidate) => candidate.kind !== attachment.kind || candidate.path !== attachment.path,
        ),
        type: "setAttachments",
      });
    },
    [dispatch, inputAttachments],
  );

  return {
    attachmentUploadPending,
    fileAttachmentInputRef,
    handleDropFiles,
    handlePickedFiles,
    hasPendingUploads,
    imageAttachmentInputRef,
    pickAttachments,
    removeAttachment,
  };
}
