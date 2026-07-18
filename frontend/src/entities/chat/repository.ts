import { getPlatform } from "../../shared/platform/platform";
import type {
  ChatCommand,
  ChatCommandResult,
  ChatHistoryEntry,
  ChatLaunchPayload,
  ChatRuntimeProcessState,
  ChatSnapshot,
  RuntimeDependencyInstallInput,
  RuntimeDependencyInstallResult,
  TaskProgressOptions,
} from "../../shared/platform/types";
import type { ChatThemePayload } from "../../shared/theme/chatChromeTheme";
import type { ChatThemeManifest, ChatThemeSummary, SaveChatThemeInput } from "../../shared/theme/chatTheme";
import type { ChatStageEvent } from "../../shared/platform/types";

export const chatQueryKey = ["chat"] as const;
export const chatRuntimeStatusQueryKey = ["chat", "runtime-status"] as const;
export const chatThemeQueryKey = ["chat", "themes"] as const;

export { runtimeStatusFromSnapshot } from "../../shared/platform/chatRuntimeStatus";

export function getChatSnapshot(): Promise<ChatSnapshot> {
  return getPlatform().chat.getSnapshot();
}

export function getChatRuntimeStatus(): Promise<ChatRuntimeProcessState> {
  return getPlatform().chat.getRuntimeStatus();
}

export function closeChat(): Promise<ChatSnapshot> {
  return getPlatform().chat.close();
}

export function getChatTheme(): Promise<ChatThemePayload> {
  return getPlatform().chat.getTheme();
}

export function launchChat(
  payload: ChatLaunchPayload,
  options?: TaskProgressOptions<ChatSnapshot>,
): Promise<ChatSnapshot> {
  return getPlatform().chat.launch(payload, options);
}

export function installMissingRuntimeDependency(
  input: RuntimeDependencyInstallInput,
  options?: TaskProgressOptions<RuntimeDependencyInstallResult>,
): Promise<RuntimeDependencyInstallResult> {
  return getPlatform().runtime.installMissingDependency(input, options);
}

export function resumeLastChat(options?: TaskProgressOptions<ChatSnapshot>): Promise<ChatSnapshot> {
  return getPlatform().chat.resumeLast(options);
}

export function sendChatCommand(command: ChatCommand): Promise<ChatCommandResult> {
  return getPlatform().chat.command(command);
}

export function getChatHistory(): Promise<ChatHistoryEntry[]> {
  return getPlatform().chat.getHistory();
}

export function subscribeChat(listener: (snapshot: ChatSnapshot) => void): () => void {
  return getPlatform().chat.subscribe(listener);
}

// --- 主题 mod 系统 ---

export function listChatThemes(): Promise<ChatThemeSummary[]> {
  return getPlatform().chat.listThemes();
}

export function getChatThemeManifest(id: string): Promise<ChatThemeManifest> {
  return getPlatform().chat.getThemeManifest(id);
}

export function getActiveChatThemeId(): Promise<string> {
  return getPlatform().chat.getActiveThemeId();
}

export function setActiveChatTheme(id: string): Promise<void> {
  return getPlatform().chat.setActiveThemeId(id);
}

export function uploadChatTheme(file: File): Promise<ChatThemeSummary> {
  return getPlatform().chat.uploadTheme(file);
}

export function saveChatTheme(input: SaveChatThemeInput): Promise<ChatThemeSummary> {
  return getPlatform().chat.saveTheme(input);
}

export function deleteChatTheme(id: string): Promise<void> {
  return getPlatform().chat.deleteTheme(id);
}

// --- 实时事件流（WebSocket）---

export function subscribeChatEvents(listener: (event: ChatStageEvent) => void): () => void {
  return getPlatform().chat.subscribeEvents(listener);
}
