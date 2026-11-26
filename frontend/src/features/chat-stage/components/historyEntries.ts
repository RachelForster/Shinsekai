import {
  HIDDEN_HISTORY_LINE_PATTERN,
  HIDDEN_HISTORY_SPEAKERS,
  LEGACY_DEFAULT_USER_SPEAKER,
  LOCAL_TIME_PREFIX_PATTERN,
} from "../../../shared/constants";
import { translateRuntimeMessage } from "../../../shared/i18n";
import type { ChatHistoryEntry } from "../../../shared/platform/types";

const defaultUserDisplayName = LEGACY_DEFAULT_USER_SPEAKER;
const hiddenSystemHistorySpeakers = new Set<string>(HIDDEN_HISTORY_SPEAKERS);

export const historyRenderBatchSize = 120;

export interface HistoryRowDialog {
  body: string;
  localTime: string;
  speaker: string;
}

export interface HistoryRowItem {
  dialog: HistoryRowDialog;
  entry: ChatHistoryEntry;
  localTime: string;
  originalIndex: number;
}

export function normalizeUserDisplayName(value?: string) {
  const trimmed = value?.trim();
  if (!trimmed || trimmed === defaultUserDisplayName) {
    return translateRuntimeMessage("ops.chatStage.defaultUserSpeaker");
  }
  return trimmed;
}

function userSpeakerPrefixPattern(userDisplayName: string) {
  const names = [defaultUserDisplayName, userDisplayName]
    .map((name) => name.trim())
    .filter(Boolean)
    .filter((name, index, list) => list.indexOf(name) === index)
    .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`^\\s*(${names.join("|")})\\s*[：:]\\s*([\\s\\S]*)$`);
}

function historySpeakerFallback(
  role: ChatHistoryEntry["role"],
  userDisplayName: string,
  labels: Record<ChatHistoryEntry["role"], string>,
) {
  if (role === "user") {
    return userDisplayName;
  }
  return labels[role] ?? labels.system;
}

export function historyEntryLocalTime(entry: ChatHistoryEntry) {
  const raw = entry.createdAt;
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    return "";
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function splitHistoryEntryText(
  entry: ChatHistoryEntry,
  userDisplayName: string,
  labels: Record<ChatHistoryEntry["role"], string>,
): HistoryRowDialog {
  const userName = normalizeUserDisplayName(userDisplayName);
  if (entry.role === "user") {
    const userMatch = entry.text.match(userSpeakerPrefixPattern(userName));
    return {
      body: (userMatch?.[2] ?? entry.text).trimStart(),
      localTime: historyEntryLocalTime(entry),
      speaker: userMatch?.[1] === defaultUserDisplayName ? userName : userMatch?.[1]?.trim() || userName,
    };
  }
  const match = entry.text.match(/^\s*([^：:\n]{1,36})\s*[：:]\s*([\s\S]*)$/);
  if (!match) {
    return { body: entry.text, localTime: "", speaker: historySpeakerFallback(entry.role, userName, labels) };
  }
  return {
    body: match[2]?.trimStart() ?? "",
    localTime: "",
    speaker: match[1]?.trim() || historySpeakerFallback(entry.role, userName, labels),
  };
}

export function historyEntryTone(role: ChatHistoryEntry["role"]) {
  if (role === "user") return "user";
  if (role === "options") return "options";
  if (role === "system") return "system";
  return "assistant";
}

function normalizeHistorySpeaker(value: string) {
  return value.trim().toLocaleLowerCase();
}

export function isHiddenSystemHistoryEntry(entry: ChatHistoryEntry, dialog: { speaker: string }) {
  if (entry.role !== "system") {
    return false;
  }
  if (hiddenSystemHistorySpeakers.has(normalizeHistorySpeaker(dialog.speaker))) {
    return true;
  }
  return HIDDEN_HISTORY_LINE_PATTERN.test(entry.text);
}

export function normalizeHistorySearch(value: string) {
  return value.trim().toLocaleLowerCase();
}

export function shareableUserText(text: string) {
  return text
    .replace(LOCAL_TIME_PREFIX_PATTERN, "")
    .replace(/(?:\s*\[(?:image|file):[^\]\r\n]*\])+\s*$/i, "")
    .trim();
}

export function sameHistoryMessage(source: ChatHistoryEntry, target: ChatHistoryEntry) {
  if (
    source.id !== target.id ||
    source.role !== target.role ||
    source.dialogId !== target.dialogId ||
    source.createdAt !== target.createdAt
  ) {
    return false;
  }
  if (source.role !== "user" || source.text === target.text) return source.text === target.text;
  const normalized = (text: string) => {
    const prefix = text.match(/^\s*([^：:\n]{1,120})[：:]\s*/);
    return `${prefix?.[1].trim() ?? ""}:${shareableUserText(text.slice(prefix?.[0].length ?? 0))}`;
  };
  return normalized(source.text) === normalized(target.text);
}
