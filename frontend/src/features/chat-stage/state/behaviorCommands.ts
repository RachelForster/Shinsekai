import type {
  ChatBehaviorChoiceOption,
  ChatBehaviorCommandPayload,
  ChatBehaviorState,
  ChatOption,
  ChatRuntimeStatus,
  ChatToolConfirmation,
} from "../../../shared/platform/types";

let behaviorCommandSequence = 0;

export function createBehaviorCommandId(): string {
  const randomUuid = globalThis.crypto?.randomUUID;
  if (typeof randomUuid === "function") {
    return randomUuid.call(globalThis.crypto);
  }
  behaviorCommandSequence += 1;
  return `behavior-${Date.now()}-${behaviorCommandSequence}`;
}

export function isBehaviorChoiceOption(option: ChatOption): option is ChatBehaviorChoiceOption {
  return typeof option !== "string" && "kind" in option && option.kind === "behavior-option";
}

export function chatOptionKey(option: ChatOption): string {
  if (typeof option === "string") {
    return option;
  }
  if (isBehaviorChoiceOption(option)) {
    return `behavior:${option.expectedStateVersion}:${option.id}`;
  }
  return `${option.expectedRevision}:${option.id}`;
}

export function isBehaviorFreeTextBlocked(behavior?: ChatBehaviorState | null): boolean {
  const policy = behavior?.stagePolicy;
  if (!policy) {
    return false;
  }
  return Boolean(policy.hideInputLayer || policy.allowFreeTextInterject === false);
}

export function isPlaybackSettledForBehavior(status: ChatRuntimeStatus): boolean {
  return status !== "generating" && status !== "streaming" && status !== "speaking" && status !== "replaying";
}

export function resolveBehaviorOptions(state: {
  behavior?: ChatBehaviorState | null;
  characterName?: string;
  dialogHtml?: string;
  dialogText?: string;
  error?: string;
  options: ChatOption[];
  status: ChatRuntimeStatus;
  toolConfirmation?: ChatToolConfirmation | null;
}): ChatBehaviorChoiceOption[] {
  if (state.options.length > 0 || state.toolConfirmation) {
    return [];
  }
  const behavior = state.behavior;
  const rawOptions = behavior?.options;
  if (!behavior || !rawOptions?.length || !isPlaybackSettledForBehavior(state.status)) {
    return [];
  }
  const hasDialogContent = Boolean(state.error || state.dialogHtml || state.dialogText || state.characterName);
  if (behavior.stagePolicy.playbackEndAction !== "show_options" && hasDialogContent) {
    return [];
  }
  return rawOptions.map((option) => ({
    action: option.action,
    enabled: true,
    expectedStateVersion: behavior.stateVersion,
    id: option.id,
    kind: "behavior-option",
    label: option.label,
    payload: option.payload,
  }));
}

export function buildBehaviorOptionCommand(option: ChatBehaviorChoiceOption): ChatBehaviorCommandPayload {
  return {
    action: option.action,
    commandId: createBehaviorCommandId(),
    expectedStateVersion: option.expectedStateVersion,
    payload: {
      optionId: option.id,
      ...(option.payload ?? {}),
    },
  };
}

export function buildBehaviorAdvanceCommand(behavior?: ChatBehaviorState | null): ChatBehaviorCommandPayload | null {
  if (!behavior || behavior.stagePolicy.playbackEndAction !== "auto_advance") {
    return null;
  }
  return {
    action: "advance",
    commandId: createBehaviorCommandId(),
    expectedStateVersion: behavior.stateVersion,
    payload: {
      trigger: "playback_end",
    },
  };
}
