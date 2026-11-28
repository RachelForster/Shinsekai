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

export interface ChatBehaviorChoiceOption extends ChatBehaviorOption {
  kind: "behavior-option";
  enabled: boolean;
  expectedStateVersion: number;
}

export interface ChatBehaviorState {
  behaviorId: string;
  pluginId?: string;
  stateVersion: number;
  stagePolicy: ChatStagePolicy;
  hud?: Record<string, unknown>;
  options?: ChatBehaviorOption[];
  casting?: Record<string, unknown>;
}

export interface PluginBehaviorEvent {
  eventType: string;
  payload: Record<string, unknown>;
  pluginId: string;
  seq: number;
}

export interface ChatBehaviorCommandPayload {
  commandId: string;
  action: string;
  expectedStateVersion: number;
  payload?: Record<string, unknown>;
}
