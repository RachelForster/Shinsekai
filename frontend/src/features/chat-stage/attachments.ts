import type { ChatAttachmentInput } from "../../shared/platform/types";

export const CHAT_ATTACHMENT_LIMIT = 8;
export const CHAT_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif"];

export function attachmentNameFromPath(path: string) {
  const normalized = path.trim().replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() || normalized || path;
}

export function mergeChatAttachments(
  current: ChatAttachmentInput[],
  kind: ChatAttachmentInput["kind"],
  paths: string[],
) {
  const merged = current.map((attachment) => ({ ...attachment }));
  const known = new Set(merged.map((attachment) => `${attachment.kind}\0${attachment.path}`));
  for (const rawPath of paths) {
    const path = rawPath.trim();
    const key = `${kind}\0${path}`;
    if (!path || known.has(key) || merged.length >= CHAT_ATTACHMENT_LIMIT) {
      continue;
    }
    known.add(key);
    merged.push({ kind, name: attachmentNameFromPath(path), path });
  }
  return merged;
}

export function chatAttachmentDisplayText(text: string, attachments: ChatAttachmentInput[]) {
  const labels = attachments.map((attachment) => `[${attachment.kind}: ${attachment.name}]`).join(" ");
  return [text.trim(), labels].filter(Boolean).join("\n");
}
