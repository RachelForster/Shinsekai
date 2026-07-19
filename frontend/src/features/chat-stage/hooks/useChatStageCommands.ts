import { useCallback, useState, type Dispatch } from "react";

import { getChatHistory, sendChatCommand } from "../../../entities/chat/repository";
import type { MessageKey } from "../../../shared/i18n";
import type { ChatCommand } from "../../../shared/platform/types";
import type { ToastPayload } from "../../../shared/ui";
import type { ChatStageAction } from "../chatState";

export function useChatStageCommands({
  confirmClearHistory,
  dispatch,
  operationFailedTitle,
  setConfirmClearHistory,
  showToast,
  t,
}: {
  confirmClearHistory: boolean;
  dispatch: Dispatch<ChatStageAction>;
  operationFailedTitle: string;
  setConfirmClearHistory: (value: boolean) => void;
  showToast: (options: ToastPayload) => void;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
}) {
  const [historyLoading, setHistoryLoading] = useState(false);

  const refreshHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const historyEntries = await getChatHistory();
      dispatch({ historyEntries, type: "setHistoryEntries" });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.error.commandFallback"),
        title: operationFailedTitle,
      });
    } finally {
      setHistoryLoading(false);
    }
  }, [dispatch, operationFailedTitle, showToast, t]);

  const sendCommand = useCallback(
    async (command: ChatCommand) => {
      if (command.type === "clear-history" && !confirmClearHistory) {
        setConfirmClearHistory(true);
        return;
      }
      try {
        const snapshot = await sendChatCommand(command);
        const commandAppliedByEventStream = [
          "cancel-input-batch",
          "flush-input-batch",
          "send-message",
          "submit-option",
        ].includes(command.type);
        if (command.type !== "copy-history" && !commandAppliedByEventStream) {
          dispatch({ snapshot, type: "hydrate" });
        }
        if (command.type === "copy-history") {
          showToast({ kind: "success", title: t("chat.toast.historyCopied") });
        }
        if (command.type === "open-history") {
          showToast({
            kind: "success",
            message: snapshot.openedPath || snapshot.historyPath,
            title: t("chat.toast.historyOpened"),
          });
        }
        if (command.type === "clear-history") {
          setConfirmClearHistory(false);
          showToast({ kind: "success", title: t("chat.toast.historyCleared") });
        }
      } catch (error) {
        if (command.type === "send-message" || command.type === "submit-option") {
          dispatch({ source: command.type, type: "rollbackUserSubmission" });
        } else {
          dispatch({ status: "idle", type: "setStatus" });
        }
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("chat.error.commandFallback"),
          title: operationFailedTitle,
        });
      }
    },
    [confirmClearHistory, dispatch, operationFailedTitle, setConfirmClearHistory, showToast, t],
  );

  return { historyLoading, refreshHistory, sendCommand };
}
