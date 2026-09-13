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
  TemplateLaunchSession,
} from "../../shared/platform/types";
import type { ChatThemePayload } from "../../shared/theme/chatChromeTheme";
import type { ChatThemeManifest, ChatThemeSummary, SaveChatThemeInput } from "../../shared/theme/chatTheme";
import type { ChatStageEvent } from "../../shared/platform/types";

export const chatQueryKey = ["chat"] as const;
export const conversationsQueryKey = ["chat", "conversations"] as const;

export const listConversations = () => getPlatform().chat.listConversations();
export const prepareConversation = (id: string) => getPlatform().chat.prepareConversation(id);
export const getCurrentConversation = () => getPlatform().chat.getCurrentConversation();
export const reconfigureConversation = (
  id: string,
  payload: ChatLaunchPayload,
  options?: TaskProgressOptions<ChatSnapshot>,
) => getPlatform().chat.reconfigureConversation(id, payload, options);
export const renameConversation = (id: string, title: string) => getPlatform().chat.renameConversation(id, title);

export async function getConversationSession(id: string): Promise<TemplateLaunchSession> {
  const payload = await prepareConversation(id);
  return {
    maxDialogItems: 0,
    maxSpeechChars: 0,
    useChoice: true,
    useCot: true,
    useEffect: true,
    useNarration: true,
    useStat: false,
    useTranslation: true,
    voiceLanguage: "ja",
    ...payload.editorSession,
    background: payload.backgroundName,
    effectNames: payload.effectNames ?? [],
    filenameStub: payload.templateName ?? "",
    historyPath: payload.historyPath,
    initSpritePath: payload.initSpritePath ?? "",
    mediaSelectionMode: payload.mediaSelectionMode ?? "indexed",
    roomId: payload.roomId ?? "",
    scenario: payload.scenario ?? "",
    system: payload.system ?? "",
    selectedCharacters: payload.characters,
    templateFileDropdown: payload.templateId,
    useCg: payload.useCg ?? false,
  };
}
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

export function uploadChatAttachments(files: File[]) {
  return getPlatform().chat.uploadAttachments(files);
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
