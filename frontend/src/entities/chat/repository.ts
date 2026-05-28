import { getPlatform } from "../../shared/platform/platform";
import type { ChatCommand, ChatCommandResult, ChatLaunchPayload, ChatSnapshot } from "../../shared/platform/types";
import type { ChatThemePayload } from "../../shared/theme/chatChromeTheme";

export const chatQueryKey = ["chat"] as const;

export function getChatSnapshot(): Promise<ChatSnapshot> {
  return getPlatform().chat.getSnapshot();
}

export function getChatTheme(): Promise<ChatThemePayload> {
  return getPlatform().chat.getTheme();
}

export function launchChat(payload: ChatLaunchPayload): Promise<ChatSnapshot> {
  return getPlatform().chat.launch(payload);
}

export function resumeLastChat(): Promise<ChatSnapshot> {
  return getPlatform().chat.resumeLast();
}

export function sendChatCommand(command: ChatCommand): Promise<ChatCommandResult> {
  return getPlatform().chat.command(command);
}

export function subscribeChat(listener: (snapshot: ChatSnapshot) => void): () => void {
  return getPlatform().chat.subscribe(listener);
}
