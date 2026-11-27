import { useCallback, useRef, useState, type Dispatch } from "react";

import { sendChatCommand, uploadChatAttachments } from "../../../entities/chat/repository";
import type { MessageKey } from "../../../shared/i18n";
import type {
  ChatAttachmentInput,
  ChatCommand,
  ChatOption,
  ChatSendPayload,
  ChatTurnOptions,
} from "../../../shared/platform/types";
import type { ToastPayload } from "../../../shared/ui";
import { CHAT_ATTACHMENT_LIMIT, chatAttachmentDisplayText, mergeChatAttachmentInputs } from "../attachments";
import type { VoicePlaybackSignal } from "../audio/soundPlayer";
import type { ChatStageAction, ChatStageState, ChatStageViewModel } from "../chatState";
import type { DialogTypewriterDirection } from "../dialogTypewriter";
import { useChatStageEvents } from "../hooks/useChatStageEvents";
import { useChatStageKeyboardShortcuts } from "../hooks/useChatStageKeyboardShortcuts";
import { useChatSubmissionFocus } from "../hooks/useChatSubmissionFocus";
import { useDialogTypewriter } from "../hooks/useDialogTypewriter";
import { useHoldToTalk } from "../hooks/useHoldToTalk";
import { useRecentUserInputs } from "../hooks/useRecentUserInputs";
import type { ActiveReplay } from "../replay/ReplayControls";
import {
  buildBehaviorAdvanceCommand,
  buildBehaviorOptionCommand,
  isBehaviorChoiceOption,
  isBehaviorFreeTextBlocked,
  isPlaybackSettledForBehavior,
} from "../state/behaviorCommands";

export interface UseChatStageInteractionControllerOptions {
  activeReplay: ActiveReplay | null;
  auto: boolean;
  dialogTextDirection: DialogTypewriterDirection;
  dispatch: Dispatch<ChatStageAction>;
  exitCg: () => void;
  historyDialogOpen: boolean;
  longPressTalk: boolean;
  miniAvatarActive: boolean;
  modalOpen: boolean;
  sendCommand: (command: ChatCommand) => Promise<void>;
  showToast: (options: ToastPayload) => void;
  state: ChatStageState;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
  toggleAuto: () => void;
  typewriterCps: number;
  viewModel: ChatStageViewModel;
}

export function useChatStageInteractionController({
  activeReplay,
  auto,
  dialogTextDirection,
  dispatch,
  exitCg,
  historyDialogOpen,
  longPressTalk,
  miniAvatarActive,
  modalOpen,
  sendCommand,
  showToast,
  state,
  t,
  toggleAuto,
  typewriterCps,
  viewModel,
}: UseChatStageInteractionControllerOptions) {
  const [attachmentUploadPending, setAttachmentUploadPending] = useState(false);
  const imageAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const fileAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const pendingAttachmentSlotsRef = useRef(0);
  const { recentInputs, rememberInput } = useRecentUserInputs();

  const handlePlaybackSignal = useCallback(
    (signal: VoicePlaybackSignal) => {
      void sendCommand({ payload: signal, type: "audio-playback-signal" });
    },
    [sendCommand],
  );

  const autoAdvanceDialog = useCallback(() => {
    const behavior = viewModel.behavior;
    if (isPlaybackSettledForBehavior(viewModel.status) && behavior?.stagePolicy?.playbackEndAction === "auto_advance") {
      const payload = buildBehaviorAdvanceCommand(behavior);
      if (payload) {
        void sendCommand({ payload, type: "behavior-command" });
        return;
      }
    }
    void sendCommand({ type: "dialog-advance" });
  }, [sendCommand, viewModel.behavior, viewModel.status]);

  const {
    dialogTotalCharacters,
    displayedDialog,
    queueAnimatedDialog,
    showDialogImmediately,
    showFullDialog,
    typingDialog,
  } = useDialogTypewriter({
    auto:
      (auto || viewModel.behavior?.stagePolicy?.playbackEndAction === "auto_advance") &&
      !activeReplay &&
      !state.replay &&
      !historyDialogOpen,
    characterName: viewModel.dialogCharacterName,
    dialogVisible: viewModel.layers.dialog,
    html: viewModel.dialogHtml,
    onAutoAdvance: autoAdvanceDialog,
    optionsVisible: viewModel.layers.options,
    status: viewModel.status,
    text: viewModel.dialogText,
    textDirection: dialogTextDirection,
    typewriterCps,
    paused: Boolean(state.replay?.paused),
  });

  const { stageRef, rememberSubmission } = useChatSubmissionFocus({
    blocked: modalOpen || Boolean(viewModel.toolConfirmation),
    inputDisabled: viewModel.inputDisabled,
    options: viewModel.options,
    replying:
      ["generating", "streaming", "speaking"].includes(viewModel.status) ||
      (typingDialog && viewModel.layers.dialog && !viewModel.layers.options),
    sessionId: state.sessionId,
  });

  const { replaceSession } = useChatStageEvents({
    dispatch,
    eventSeq: state.eventSeq,
    sessionId: state.sessionId,
    loadFallbackMessage: t("chat.error.loadFallback"),
    queueAnimatedDialog,
    showDialogImmediately,
  });

  const submit = async (textOverride?: string) => {
    if (
      activeReplay ||
      state.replay ||
      pendingAttachmentSlotsRef.current ||
      isBehaviorFreeTextBlocked(viewModel.behavior)
    ) {
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

  const addAttachments = (attachments: ChatAttachmentInput[]) => {
    const next = mergeChatAttachmentInputs(state.inputAttachments, attachments);
    const existing = new Set(state.inputAttachments.map((attachment) => `${attachment.kind}\0${attachment.path}`));
    const requested = new Set(
      attachments
        .map((attachment) => `${attachment.kind}\0${attachment.path.trim()}`)
        .filter((key) => !key.endsWith("\0"))
        .filter((key) => !existing.has(key)),
    );
    if (next.length - state.inputAttachments.length < requested.size) {
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
      CHAT_ATTACHMENT_LIMIT - state.inputAttachments.length - pendingAttachmentSlotsRef.current,
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

  const setDraft = useCallback(
    (text: string) => {
      dispatch({ text, type: "setDraft" });
    },
    [dispatch],
  );

  const removeAttachment = useCallback(
    (attachment: ChatAttachmentInput) => {
      dispatch({
        attachments: state.inputAttachments.filter(
          (candidate) => candidate.kind !== attachment.kind || candidate.path !== attachment.path,
        ),
        type: "setAttachments",
      });
    },
    [dispatch, state.inputAttachments],
  );

  const advanceDialog = useCallback(() => {
    if (typingDialog) {
      showFullDialog();
      return;
    }
    if (activeReplay || state.replay || !viewModel.layers.dialog || !dialogTotalCharacters) {
      return;
    }
    const behavior = viewModel.behavior;
    if (isPlaybackSettledForBehavior(viewModel.status) && behavior?.stagePolicy?.playbackEndAction === "auto_advance") {
      const payload = buildBehaviorAdvanceCommand(behavior);
      if (payload) {
        void sendCommand({ payload, type: "behavior-command" });
        return;
      }
    }
    void sendCommand({ type: "dialog-advance" });
  }, [
    activeReplay,
    state.replay,
    dialogTotalCharacters,
    sendCommand,
    showFullDialog,
    typingDialog,
    viewModel.behavior,
    viewModel.layers.dialog,
    viewModel.status,
  ]);

  useChatStageKeyboardShortcuts({
    disabled: modalOpen,
    onAdvance: advanceDialog,
    onExitCg: viewModel.layers.cg && !miniAvatarActive ? exitCg : undefined,
    onToggleAuto: toggleAuto,
  });

  useHoldToTalk({
    enabled: longPressTalk,
    disabled: modalOpen || viewModel.inputDisabled || Boolean(state.sessionClosedReason),
    onCommand: sendCommand,
  });

  return {
    advanceDialog,
    attachmentUploadPending,
    dialogTotalCharacters,
    displayedDialog,
    fileAttachmentInputRef,
    handleDropFiles,
    handlePickedFiles,
    handlePlaybackSignal,
    imageAttachmentInputRef,
    pickAttachments,
    recentInputs,
    removeAttachment,
    replaceSession,
    resolveToolConfirmation,
    setDraft,
    showDialogImmediately,
    stageRef,
    submit,
    submitOption,
    typingDialog,
    updateInputActivity,
    updateTurnOptions,
  };
}
