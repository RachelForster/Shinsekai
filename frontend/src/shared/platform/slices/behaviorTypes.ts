export type ChatPlaybackEndAction = "idle" | "auto_advance" | "show_options";

export interface ChatStagePolicy {
  hideInputLayer: boolean;
  playbackEndAction: ChatPlaybackEndAction;
  allowFreeTextInterject: boolean;
  allowUnboundSpeakers: boolean;
}

export interface ChatBehaviorOption {
  id: string;
  label: string;
  action: string;
  payload?: Record<string, unknown>;
}

export interface ChatBehaviorState {
  behaviorId: string;
  stateVersion: number;
  stagePolicy: ChatStagePolicy;
  hud?: Record<string, unknown>;
  options?: ChatBehaviorOption[];
  casting?: Record<string, unknown>;
}

export interface ChatBehaviorCommandPayload {
  commandId: string;
  action: string;
  expectedStateVersion: number;
  payload?: Record<string, unknown>;
}
