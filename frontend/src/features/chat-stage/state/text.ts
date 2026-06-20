import type { ChatRuntimeStatus } from "../../../shared/platform/types";
import type { ChatStageState } from "./types";

export const defaultUserDialogSpeaker = "你";

export function htmlToText(value: string) {
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(?:div|li|p)>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function normalizedUserDisplayName(value?: string) {
  return value?.trim() || defaultUserDialogSpeaker;
}

function isSystemPromptText(value: string) {
  const text = value.trim();
  if (!text) {
    return false;
  }
  return /^(已跳过|已选择|选择：|历史|浏览器预览历史|语音识别|正在请求|聊天会话|您的消息已提交|进程已经|当前聊天会话|实时聊天会话)/.test(
    text,
  );
}

export function normalizeTokenUsageText(value: string | undefined, status: ChatRuntimeStatus) {
  const text = value?.trim();
  if (!text || text === status) {
    return undefined;
  }
  if (/^(idle|listening|paused|generating|streaming|speaking|error)$/i.test(text)) {
    return undefined;
  }
  return text;
}

export function systemPromptTextFromState(state: ChatStageState, dialogText: string) {
  if (state.error) {
    return state.error;
  }
  const statusMessage = state.statusMessage?.trim();
  if (statusMessage && !state.characterName?.trim()) {
    return statusMessage;
  }
  if (!state.characterName?.trim() && state.dialogHtml === undefined && isSystemPromptText(dialogText)) {
    return dialogText.trim();
  }
  return undefined;
}

function userDialogPrefixPattern(userDisplayName: string) {
  const names = [defaultUserDialogSpeaker, userDisplayName]
    .map((name) => name.trim())
    .filter(Boolean)
    .filter((name, index, list) => list.indexOf(name) === index)
    .map(escapeRegExp);
  return new RegExp(`^\\s*(?:${names.join("|")})\\s*[：:]\\s*`);
}

export function normalizeDialogView(
  characterName: string | undefined,
  dialogText: string,
  dialogHtml: string | undefined,
  userDisplayName: string,
) {
  const normalizedName = characterName?.trim();
  const userName = normalizedUserDisplayName(userDisplayName);
  const prefixPattern = userDialogPrefixPattern(userName);
  if (normalizedName === defaultUserDialogSpeaker || normalizedName === userName) {
    return {
      characterName: userName,
      dialogHtml,
      dialogText: dialogText.replace(prefixPattern, ""),
    };
  }
  if (!normalizedName && dialogHtml === undefined && prefixPattern.test(dialogText)) {
    return {
      characterName: userName,
      dialogHtml,
      dialogText: dialogText.replace(prefixPattern, ""),
    };
  }
  return {
    characterName,
    dialogHtml,
    dialogText,
  };
}
