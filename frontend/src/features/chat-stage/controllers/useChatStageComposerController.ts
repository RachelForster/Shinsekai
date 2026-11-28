import { useCallback, type Dispatch } from "react";

import { sendChatCommand } from "../../../entities/chat/repository";
import type { MessageKey } from "../../../shared/i18n";
import type { ChatCommand, ChatOption, ChatSendPayload, ChatTurnOptions } from "../../../shared/platform/types";
import type { ToastPayload } from "../../../shared/ui";
import { chatAttachmentDisplayText } from "../attachments";
import type { ChatStageAction, ChatStageState, ChatStageViewModel } from "../chatState";
import { useChatSubmissionFocus } from "../hooks/useChatSubmissionFocus";
import { useRecentUserInputs } from "../hooks/useRecentUserInputs";
import type { ActiveReplay } from "../replay/ReplayControls";
import {
  buildBehaviorOptionCommand,
  isBehaviorChoiceOption,
  isBehaviorFreeTextBlocked,
} from "../state/behaviorCommands";

export interface UseChatStageComposerControllerOptions {
  activeReplay: ActiveReplay | null;
  dispatch: Dispatch<ChatStageAction>;
  hasPendingUploads: () => boolean;
  modalOpen: boolean;
  sendCommand: (command: ChatCommand) => Promise<void>;
  showDialogImmediately: () => void;
  showToast: (options: ToastPayload) => void;
  state: ChatStageState;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
  typingDialog: boolean;
  viewModel: ChatStageViewModel;
}

export function useChatStageComposerController({
  activeReplay,
  dispatch,
  hasPendingUploads,
  modalOpen,
  sendCommand,
  showDialogImmediately,
  showToast,
  state,
  t,
  typingDialog,
  viewModel,
}: UseChatStageComposerControllerOptions) {
  const { recentInputs, rememberInput } = useRecentUserInputs();

  const { stageRef, rememberSubmission } = useChatSubmissionFocus({
    blocked: modalOpen || Boolean(viewModel.toolConfirmation),
    inputDisabled: viewModel.inputDisabled,
    options: viewModel.options,
    replying:
      ["generating", "streaming", "speaking"].includes(viewModel.status) ||
      (typingDialog && viewModel.layers.dialog && !viewModel.layers.options),
    sessionId: state.sessionId,
  });

  const setDraft = useCallback(
    (text: string) => {
      dispatch({ text, type: "setDraft" });
    },
    [dispatch],
  );

  const submit = async (textOverride?: string) => {
    if (activeReplay || state.replay || hasPendingUploads() || isBehaviorFreeTextBlocked(viewModel.behavior)) {
      return;
    }
    const text = (textOverride ?? viewModel.inputDraft).trim();
    const attachments = viewModel.inputAttachments.map((attachment) => ({ ...attachment }));
    if (!text && !attachments.length) {
      return;
    }
    rememberSubmission({ kind: "input" });
    rememberInput(text);
    const displayText = chatAttachmentDisplayText(text, attachments);
    const payload: string | ChatSendPayload = attachments.length ? { attachments, text } : text;
    showDialogImmediately();
    dispatch({
      queued: state.turnOptions.batchEnabled,
      source: "send-message",
      text: displayText,
      type: "submitUserMessage",
    });
    await sendCommand({ payload, type: "send-message" });
  };

  const submitOption = (option: ChatOption) => {
    if (activeReplay || state.replay) return;
    if (isBehaviorChoiceOption(option)) {
      if (!option.enabled) {
        return;
      }
      rememberSubmission({ kind: "options", index: Math.max(0, viewModel.options.indexOf(option)) });
      showDialogImmediately();
      void sendCommand({
        payload: buildBehaviorOptionCommand(option),
        type: "behavior-command",
      });
      return;
    }
    const label = typeof option === "string" ? option : option.label;
    if (typeof option !== "string" && !option.enabled) {
      return;
    }
    rememberSubmission({ kind: "options", index: Math.max(0, viewModel.options.indexOf(option)) });
    showDialogImmediately();
    dispatch({
      queued: state.turnOptions.batchEnabled,
      source: "submit-option",
      text: label,
      type: "submitUserMessage",
    });
    void sendCommand({
      payload:
        typeof option === "string"
          ? option
          : {
              choiceId: option.id,
              expectedNodeId: option.expectedNodeId,
              expectedRevision: option.expectedRevision,
              kind: "story-choice",
            },
      type: "submit-option",
    });
  };

  const resolveToolConfirmation = (action: "confirm" | "cancel") => {
    const confirmation = state.toolConfirmation;
    if (!confirmation) {
      return;
    }
    void sendCommand({
      payload: {
        action,
        confirmationId: confirmation.confirmationId,
        kind: "tool-confirmation",
      },
      type: "submit-option",
    });
  };

  const updateTurnOptions = useCallback(
    (options: ChatTurnOptions) => {
      const previous = state.turnOptions;
      dispatch({ options, type: "setTurnOptions" });
      void sendChatCommand({ payload: options, type: "update-turn-options" }).catch((error) => {
        dispatch({ options: previous, type: "setTurnOptions" });
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("chat.error.commandFallback"),
          title: t("common.operationFailed"),
        });
      });
    },
    [dispatch, showToast, state.turnOptions, t],
  );

  const updateInputActivity = useCallback((inputState: { composing: boolean; hasText: boolean }) => {
    void sendChatCommand({ payload: inputState, type: "chat-input-state" }).catch(() => undefined);
  }, []);

  return {
    recentInputs,
    resolveToolConfirmation,
    setDraft,
    stageRef,
    submit,
    submitOption,
    updateInputActivity,
    updateTurnOptions,
  };
}
