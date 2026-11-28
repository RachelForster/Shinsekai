import { useCallback, type Dispatch } from "react";

import type { MessageKey } from "../../../shared/i18n";
import type { ChatCommand, PluginBehaviorEvent } from "../../../shared/platform/types";
import type { VoicePlaybackSignal } from "../audio/soundPlayer";
import type { ChatStageAction, ChatStageState, ChatStageViewModel } from "../chatState";
import type { DialogTypewriterDirection } from "../dialogTypewriter";
import { useChatStageEvents } from "../hooks/useChatStageEvents";
import { useChatStageKeyboardShortcuts } from "../hooks/useChatStageKeyboardShortcuts";
import { useDialogTypewriter } from "../hooks/useDialogTypewriter";
import { useHoldToTalk } from "../hooks/useHoldToTalk";
import type { ActiveReplay } from "../replay/ReplayControls";
import { buildBehaviorAdvanceCommand, isPlaybackSettledForBehavior } from "../state/behaviorCommands";

export interface UseChatStageDialogPlaybackControllerOptions {
  activeReplay: ActiveReplay | null;
  auto: boolean;
  dialogTextDirection: DialogTypewriterDirection;
  dispatch: Dispatch<ChatStageAction>;
  exitCg: () => void;
  historyDialogOpen: boolean;
  longPressTalk: boolean;
  miniAvatarActive: boolean;
  modalOpen: boolean;
  onPluginBehaviorEvent?: (event: PluginBehaviorEvent) => void;
  onPluginBehaviorSessionReset?: () => void;
  sendCommand: (command: ChatCommand) => Promise<void>;
  state: ChatStageState;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
  toggleAuto: () => void;
  typewriterCps: number;
  viewModel: ChatStageViewModel;
}

export function useChatStageDialogPlaybackController({
  activeReplay,
  auto,
  dialogTextDirection,
  dispatch,
  exitCg,
  historyDialogOpen,
  longPressTalk,
  miniAvatarActive,
  modalOpen,
  onPluginBehaviorEvent,
  onPluginBehaviorSessionReset,
  sendCommand,
  state,
  t,
  toggleAuto,
  typewriterCps,
  viewModel,
}: UseChatStageDialogPlaybackControllerOptions) {
  const handlePlaybackSignal = useCallback(
    (signal: VoicePlaybackSignal) => {
      void sendCommand({ payload: signal, type: "audio-playback-signal" });
    },
    [sendCommand],
  );

  const sendDialogAdvance = useCallback(() => {
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
    onAutoAdvance: sendDialogAdvance,
    optionsVisible: viewModel.layers.options,
    status: viewModel.status,
    text: viewModel.dialogText,
    textDirection: dialogTextDirection,
    typewriterCps,
    paused: Boolean(state.replay?.paused),
  });

  const { replaceSession } = useChatStageEvents({
    dispatch,
    eventSeq: state.eventSeq,
    sessionId: state.sessionId,
    loadFallbackMessage: t("chat.error.loadFallback"),
    onPluginBehaviorEvent,
    onPluginBehaviorSessionReset,
    queueAnimatedDialog,
    showDialogImmediately,
  });

  const advanceDialog = useCallback(() => {
    if (typingDialog) {
      showFullDialog();
      return;
    }
    if (activeReplay || state.replay || !viewModel.layers.dialog || !dialogTotalCharacters) {
      return;
    }
    sendDialogAdvance();
  }, [
    activeReplay,
    dialogTotalCharacters,
    sendDialogAdvance,
    showFullDialog,
    state.replay,
    typingDialog,
    viewModel.layers.dialog,
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
    dialogTotalCharacters,
    displayedDialog,
    handlePlaybackSignal,
    replaceSession,
    showDialogImmediately,
    typingDialog,
  };
}
