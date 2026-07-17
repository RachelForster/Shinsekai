import {
  normalizeDialogView,
  normalizedUserDisplayName,
  normalizeTokenUsageText,
  systemPromptTextFromState,
} from "./text";
import type { ChatStageState, ChatStageViewModel } from "./types";

export function buildChatStageViewModel(state: ChatStageState): ChatStageViewModel {
  const dialog = normalizeDialogView(
    state.error ? undefined : state.characterName,
    state.error ?? state.dialogText,
    state.error ? undefined : state.dialogHtml,
    state.userDisplayName,
  );
  const tokenUsageText = normalizeTokenUsageText(state.numericInfo, state.status);
  const systemPromptText = systemPromptTextFromState(state, dialog.dialogText);
  const systemMessageText = state.systemMessageText?.trim();
  const layers = {
    ...state.layers,
    dialog:
      state.layers.dialog && !systemMessageText && !systemPromptText && Boolean(dialog.dialogHtml || dialog.dialogText),
    notification: Boolean(state.notificationText || systemMessageText || systemPromptText),
  };
  return {
    backgroundPath: state.backgroundPath,
    bgmPath: state.bgmPath,
    busyText: state.busyText,
    cgPath: state.cgPath,
    dialogCharacterName: systemPromptText ? undefined : dialog.characterName,
    dialogHtml: systemPromptText ? undefined : dialog.dialogHtml,
    dialogText: systemPromptText ? "" : dialog.dialogText,
    inputDisabled: !state.layers.input || state.status === "generating" || state.status === "streaming",
    inputDraft: state.inputDraft,
    layers,
    notificationText: state.notificationText || systemMessageText || systemPromptText,
    options: state.options,
    sprites: state.sprites,
    status: state.status,
    statusText: state.status,
    tokenUsageText,
    transportMode: state.transportMode,
    transportState: state.transportState,
    userDisplayName: normalizedUserDisplayName(state.userDisplayName),
    voiceLanguage: state.voiceLanguage,
  };
}
