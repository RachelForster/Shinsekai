import {
  normalizeDialogView,
  normalizedUserDisplayName,
  normalizeTokenUsageText,
  systemPromptTextFromState,
} from "./text";
import type { ChatStageState, ChatStageViewModel } from "./types";
import { chatStageSpriteCharacterName } from "./sprites";

function thinkingCharacterName(state: ChatStageState): string | undefined {
  if (!state.optimisticSubmission || state.status !== "generating" || state.error || state.sessionClosedReason)
    return undefined;
  const user = normalizedUserDisplayName(state.userDisplayName);
  // A reply can arrive before its status update; return attention immediately.
  if (state.characterName?.trim() && state.characterName.trim() !== user) return undefined;
  const names = [...new Set(state.sprites.map(chatStageSpriteCharacterName).filter(Boolean))];
  const previous = state.optimisticSubmission.previous.characterName?.trim();
  if (previous && previous !== user && names.includes(previous)) return previous;
  // An unknown addressee in a group is safer than choosing the first character.
  return names.length === 1 ? names[0] : undefined;
}

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
    asrEnabled: Boolean(state.asrEnabled),
    asrLoading: Boolean(state.asrLoading),
    asrRunning: Boolean(state.asrRunning),
    backgroundPath: state.backgroundPath,
    bgmPath: state.bgmPath,
    busyText: state.busyText,
    cgPath: state.cgPath,
    dialogCharacterName: systemPromptText ? undefined : dialog.characterName,
    thinkingCharacterName: thinkingCharacterName(state),
    dialogHtml: systemPromptText ? undefined : dialog.dialogHtml,
    dialogText: systemPromptText ? "" : dialog.dialogText,
    inputAttachments: state.inputAttachments,
    inputDisabled:
      Boolean(state.toolConfirmation) ||
      !state.layers.input ||
      ((state.status === "generating" || state.status === "streaming") && !state.turnOptions.interruptEnabled),
    inputDraft: state.inputDraft,
    layers,
    notificationText,
    options: state.options,
    sprites: state.sprites,
    stats: state.stats ?? [],
    story: state.story,
    status: state.status,
    statusText: state.status,
    tokenUsageText,
    toolConfirmation: state.toolConfirmation,
    transportMode: state.transportMode,
    transportState: state.transportState,
    userDisplayName: normalizedUserDisplayName(state.userDisplayName),
    voiceLanguage: state.voiceLanguage,
  };
}
