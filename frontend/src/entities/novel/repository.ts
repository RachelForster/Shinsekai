import { getPlatform } from "../../shared/platform/platform";
import type { NovelCastBindingInput, NovelJumpChapterInput, NovelLaunchRequest } from "../../shared/platform/types";

export const novelDocumentsQueryKey = ["novel", "documents"] as const;

export function listNovelDocuments() {
  return getPlatform().novel.listDocuments();
}

export function importNovelDocument(file: File) {
  return getPlatform().novel.importDocument(file);
}

export function getNovelDocument(docId: string) {
  return getPlatform().novel.getDocument(docId);
}

export function deleteNovelDocument(docId: string) {
  return getPlatform().novel.deleteDocument(docId);
}

export function extractNovelCast(docId: string) {
  return getPlatform().novel.extractCast(docId);
}

export function saveNovelCasting(conversationId: string, bindings: NovelCastBindingInput[]) {
  return getPlatform().novel.saveCasting(conversationId, bindings);
}

export function prepareNovelLaunchPayload(input: NovelLaunchRequest) {
  return getPlatform().novel.prepareLaunchPayload(input);
}

export function jumpNovelChapter(input: NovelJumpChapterInput) {
  return getPlatform().novel.jumpChapter(input);
}
