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

export function withResolvedLayers(state: ChatStageState): ChatStageState {
  return {
    ...state,
    layers: {
      ...state.layers,
      background: true,
      busy: Boolean(state.busyText),
      cg: Boolean(state.cgPath),
      dialog: Boolean(state.error || state.dialogHtml || state.dialogText || state.characterName),
      input: !state.sessionClosedReason,
      notification: Boolean(state.notificationText),
      options: state.options.length > 0,
      sprites: !state.cgPath && state.sprites.length > 0,
      toolbar: true,
    },
  };
}
