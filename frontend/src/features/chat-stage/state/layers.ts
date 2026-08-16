import { normalizedUserDisplayName } from "./text";
import type { ChatOption } from "../../../shared/platform/types";
import type { ChatStageLayers, ChatStageState } from "./types";

export function defaultLayers(): ChatStageLayers {
  return {
    background: true,
    busy: false,
    cg: false,
    dialog: false,
    input: true,
    notification: false,
    options: false,
    sprites: false,
    toolbar: true,
  };
}

export function clearTransientNotificationState(state: ChatStageState) {
  return {
    ...state,
    notificationText: undefined,
    sessionClosedReason: undefined,
  };
}

export function dialogHoldKey(state: Pick<ChatStageState, "dialogText" | "story">): string {
  return `${state.story?.currentNodeId ?? ""}:${state.story?.revision ?? ""}:${state.dialogText}`;
}

function hasHeldStoryOptions(options: ChatOption[]): boolean {
  return options.some((option) => typeof option !== "string" && option.source === "story");
}

export function optionsHeldForDialog(state: ChatStageState): boolean {
  const hasDialog = Boolean(state.dialogHtml?.trim() || state.dialogText.trim());
  if (!hasDialog || !hasHeldStoryOptions(state.options) || state.toolConfirmation) {
    return false;
  }
  const speaker = state.characterName?.trim() ?? "";
  const userName = normalizedUserDisplayName(state.userDisplayName);
  if (speaker && speaker === userName) {
    return false;
  }
  return dialogHoldKey(state) !== state.revealedOptionsAfterDialogKey;
}

export function withResolvedLayers(state: ChatStageState): ChatStageState {
  const holdingOptions = optionsHeldForDialog(state);
  const optionsVisible =
    !holdingOptions && (state.options.length > 0 || Boolean(state.toolConfirmation));
  return {
    ...state,
    layers: {
      ...state.layers,
      background: true,
      busy: Boolean(state.busyText),
      cg: Boolean(state.cgPath),
      dialog: !optionsVisible && Boolean(state.error || state.dialogHtml || state.dialogText || state.characterName),
      input: !state.sessionClosedReason,
      notification: Boolean(state.notificationText),
      options: optionsVisible,
      sprites: !state.cgPath && state.sprites.length > 0,
      toolbar: true,
    },
  };
}
