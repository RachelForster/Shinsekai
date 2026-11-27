import type { HttpTransport } from "../httpTransport";
import type { ChatLaunchPayload, ChatSnapshot, ConversationSummary } from "./chatTypes";
import type { NovelCastExtractionResult, NovelDocumentDetail, NovelDocumentSummary, NovelPlatform } from "./novelTypes";

export function createNovelHttpPlatform(transport: HttpTransport): NovelPlatform {
  const { encodePath, requestJson, uploadFiles } = transport;

  return {
    async listDocuments() {
      const res = await requestJson<{ documents: NovelDocumentSummary[] }>("/api/novel/documents");
      return res.documents ?? [];
    },
    async importDocument(file) {
      const res = await uploadFiles<{ document: NovelDocumentDetail }>("/api/novel/documents/import", [file]);
      return res.document;
    },
    async getDocument(docId) {
      const res = await requestJson<{ document: NovelDocumentDetail }>(`/api/novel/documents/${encodePath(docId)}`);
      return res.document;
    },
    deleteDocument: (docId) =>
      requestJson<{ ok: boolean; docId: string }>(`/api/novel/documents/${encodePath(docId)}`, {
        method: "DELETE",
      }),
    extractCast: (docId) =>
      requestJson<NovelCastExtractionResult>(`/api/novel/documents/${encodePath(docId)}/extract-cast`, {
        method: "POST",
        body: "{}",
      }),
    async saveCasting(conversationId, bindings, nameMode) {
      const res = await requestJson<{ conversation: ConversationSummary }>("/api/novel/casting", {
        method: "POST",
        body: JSON.stringify({
          conversationId,
          bindings,
          ...(nameMode ? { nameMode } : {}),
        }),
      });
      return res.conversation;
    },
    async prepareLaunchPayload(input) {
      const res = await requestJson<{ payload: ChatLaunchPayload }>("/api/novel/launch-payload", {
        method: "POST",
        body: JSON.stringify(input),
      });
      return res.payload;
    },
    jumpChapter: (input) =>
      requestJson<{ ok: boolean; chat: ChatSnapshot }>("/api/novel/jump-chapter", {
        method: "POST",
        body: JSON.stringify(input),
      }),
  };
}
