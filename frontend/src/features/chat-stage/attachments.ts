import type { ChatAttachmentInput } from "../../shared/platform/types";
import { normalizePathSeparatorsForIdentity } from "../../shared/paths/pathContract";

export const CHAT_ATTACHMENT_LIMIT = 8;
export const CHAT_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif"];

export function attachmentNameFromPath(path: string) {
  const normalized = normalizePathSeparatorsForIdentity(path);
  return normalized.split("/").filter(Boolean).pop() || normalized || path;
}

export function chatAttachmentIdentityKey(attachment: Pick<ChatAttachmentInput, "kind" | "path">) {
  return `${attachment.kind}\0${normalizePathSeparatorsForIdentity(attachment.path)}`;
}

export function mergeChatAttachments(
  current: ChatAttachmentInput[],
  kind: ChatAttachmentInput["kind"],
  paths: string[],
) {
  return mergeChatAttachmentInputs(
    current,
    paths.map((path) => ({ kind, name: attachmentNameFromPath(path), path })),
  );
}

export function mergeChatAttachmentInputs(current: ChatAttachmentInput[], additions: ChatAttachmentInput[]) {
  const merged = current.map((attachment) => ({ ...attachment }));
  const known = new Set(merged.map(chatAttachmentIdentityKey));
  for (const addition of additions) {
    const path = addition.path;
    const key = chatAttachmentIdentityKey(addition);
    if (!path || known.has(key) || merged.length >= CHAT_ATTACHMENT_LIMIT) {
      continue;
    }
    known.add(key);
    merged.push({
      kind: addition.kind,
      name: addition.name.trim() || attachmentNameFromPath(path),
      path,
    });
  }
  return merged;
}

export function chatAttachmentDisplayText(text: string, attachments: ChatAttachmentInput[]) {
  const labels = attachments.map((attachment) => `[${attachment.kind}: ${attachment.name}]`).join(" ");
  return [text.trim(), labels].filter(Boolean).join("\n");
}
