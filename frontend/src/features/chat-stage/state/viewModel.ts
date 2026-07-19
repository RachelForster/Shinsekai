import {
  normalizeDialogView,
  normalizedUserDisplayName,
  normalizeTokenUsageText,
  systemPromptTextFromState,
} from "./text";
import type { ChatStageState, ChatStageViewModel } from "./types";

export function buildChatStageViewModel(state: ChatStageState): ChatStageViewModel {
  const pendingBatchText = (state.turnState.pendingMessages ?? []).filter((message) => message.trim()).join("\n");
  const dialog = normalizeDialogView(
    state.error ? undefined : pendingBatchText ? normalizedUserDisplayName(state.userDisplayName) : state.characterName,
    state.error ?? (pendingBatchText || state.dialogText),
    state.error || pendingBatchText ? undefined : state.dialogHtml,
    state.userDisplayName,
  );
  const tokenUsageText = normalizeTokenUsageText(state.numericInfo, state.status);
  const systemPromptText = pendingBatchText ? undefined : systemPromptTextFromState(state, dialog.dialogText);
  const systemMessageText = pendingBatchText ? undefined : state.systemMessageText?.trim();
  const notificationText = pendingBatchText
    ? undefined
    : state.notificationText || systemMessageText || systemPromptText;
  const layers = {
    ...state.layers,
    dialog:
      (state.layers.dialog || Boolean(pendingBatchText)) &&
      !systemMessageText &&
      !systemPromptText &&
      Boolean(dialog.dialogHtml || dialog.dialogText),
    notification: Boolean(notificationText),
    options: pendingBatchText ? false : state.layers.options,
  };
  return {
    backgroundPath: state.backgroundPath,
    bgmPath: state.bgmPath,
    busyText: state.busyText,
    cgPath: state.cgPath,
    dialogCharacterName: systemPromptText ? undefined : dialog.characterName,
    dialogHtml: systemPromptText ? undefined : dialog.dialogHtml,
    dialogText: systemPromptText ? "" : dialog.dialogText,
    inputDisabled:
      !state.layers.input ||
      ((state.status === "generating" || state.status === "streaming") && !state.turnOptions.interruptEnabled),
    inputDraft: state.inputDraft,
    layers,
    notificationText,
    options: state.options,
    sprites: state.sprites,
    stats: state.stats ?? [],
    status: state.status,
    statusText: state.status,
    tokenUsageText,
    transportMode: state.transportMode,
    transportState: state.transportState,
    userDisplayName: normalizedUserDisplayName(state.userDisplayName),
    voiceLanguage: state.voiceLanguage,
  };
}
