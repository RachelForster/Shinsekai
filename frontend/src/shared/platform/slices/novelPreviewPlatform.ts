import type { ChatLaunchPayload } from "./chatTypes";
import { PlatformRequestError } from "../errors";
import { clone, delay, createBrowserPreviewContext } from "./previewContext";
import type { NovelChapterTocEntry, NovelDocumentDetail, NovelPlatform } from "./novelTypes";

type BrowserPreviewContext = ReturnType<typeof createBrowserPreviewContext>;

function splitChaptersFromText(rawText: string): NovelChapterTocEntry[] {
  const lines = rawText.split(/\r?\n/);
  const headingPattern = /^(?:#{1,3}\s+.+|Chapter\s+\d+\b.*)$/i;
  const matchedTitles = lines.map((line) => line.trim()).filter((line) => headingPattern.test(line));
  const titles = matchedTitles.length > 0 ? matchedTitles.slice(0, 64) : ["Chapter 1"];
  return titles.map((title, index) => ({
    index,
    title,
    startChunkIndex: index * 2,
    chunkCount: 2,
    pageStart: null,
    pageEnd: null,
  }));
}

export function createNovelPreviewPlatform(ctx?: BrowserPreviewContext): NovelPlatform {
  const docs = new Map<string, NovelDocumentDetail>();

  return {
    listDocuments: () =>
      delay(
        [...docs.values()].map(({ manifest, chapters }) => ({ manifest, chapters })),
        60,
      ),
    async importDocument(file) {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "txt";
      if (ext !== "txt" && ext !== "md" && ext !== "markdown") {
        throw new PlatformRequestError("PDF import requires the desktop bridge runtime.", 400, "local_app_required");
      }
      const text = await file.text();
      if (!text.trim()) {
        throw new PlatformRequestError("Document has no readable content.", 400, "document.empty_content");
      }
      const docId = `preview-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      const title = file.name.replace(/\.[^.]+$/, "") || docId;
      const chapters = splitChaptersFromText(text);
      const detail: NovelDocumentDetail = {
        manifest: {
          docId,
          title,
          sourceFormat: ext === "txt" ? "txt" : "markdown",
          sourceFilename: file.name,
          totalChars: text.length,
          totalChunks: Math.max(1, chapters.length * 2),
          totalChapters: chapters.length,
          createdAtMs: Date.now(),
          pageCount: null,
          chunkConfig: { maxChars: 1400, overlapChars: 160, lookaheadChars: 400 },
        },
        chapters,
        sampleChunks: [
          {
            chunkId: `${docId}-chunk-0`,
            index: 0,
            chapterIndex: 0,
            text: text.slice(0, 1400),
          },
        ],
      };
      docs.set(docId, detail);
      return delay(detail, 60);
    },
    async getDocument(docId) {
      const found = docs.get(docId);
      if (!found) {
        throw new PlatformRequestError("Document not found.", 404, "novel.document_not_found", { docId });
      }
      return delay(found, 40);
    },
    async deleteDocument(docId) {
      if (!docs.has(docId)) {
        throw new PlatformRequestError("Document not found.", 404, "novel.document_not_found", { docId });
      }
      docs.delete(docId);
      return delay({ ok: true, docId }, 40);
    },
    async extractCast(docId) {
      const found = docs.get(docId);
      if (!found) {
        throw new PlatformRequestError("Document not found.", 404, "novel.document_not_found", { docId });
      }
      const availableCharacters = (ctx?.config.characters ?? []).map((char) => ({
        name: char.name,
        brief: char.character_brief || "",
      }));
      return delay({ docId, characters: [], availableCharacters }, 80);
    },
    async saveCasting(conversationId, bindings, nameMode) {
      const entry = ctx?.conversations.get(conversationId);
      if (!entry) {
        throw new PlatformRequestError("Conversation not found.", 404, "novel.conversation_not_found", {
          conversationId,
        });
      }
      const resolvedNameMode = nameMode ?? (entry.summary.novelNameMode || "story");
      const boundNames = [
        ...new Set(
          bindings.map((item) => item.targetCharacter?.trim()).filter((name): name is string => Boolean(name)),
        ),
      ];
      entry.summary = {
        ...entry.summary,
        characters: boundNames,
        castEntries: clone(bindings),
        novelNameMode: resolvedNameMode,
      };
      entry.payload = {
        ...entry.payload,
        characters: boundNames,
        castEntries: clone(bindings),
        nameMode: resolvedNameMode,
      };
      return delay(entry.summary, 40);
    },
    async prepareLaunchPayload(input) {
      const found = docs.get(input.docId);
      if (!found) {
        throw new PlatformRequestError("Document not found.", 404, "novel.document_not_found", {
          docId: input.docId,
        });
      }
      const bindings = input.casting ?? [];
      const boundNames = [
        ...new Set(
          bindings.map((item) => item.targetCharacter?.trim()).filter((name): name is string => Boolean(name)),
        ),
      ];
      return delay<ChatLaunchPayload>(
        {
          behaviorId: "novel_theater",
          novelDocId: found.manifest.docId,
          nameMode: input.nameMode ?? "actor",
          castEntries: clone(bindings),
          characters: boundNames,
          backgroundName: input.backgroundName ?? "",
          mediaSelectionMode: input.mediaSelectionMode ?? "indexed",
          useChoice: false,
          useNarration: true,
          useStat: false,
          useEffect: input.useEffect ?? true,
          useTranslation: input.useTranslation ?? true,
          memoryMode: "isolated",
          showInitialSprite: false,
          historyPath: input.historyPath || `preview/novel-${found.manifest.docId}.json`,
          conversationTitle: input.conversationTitle || found.manifest.title,
          templateId: "",
          templateName: found.manifest.title,
          resetHistory: false,
        },
        40,
      );
    },
    async jumpChapter(input) {
      if (!ctx) {
        throw new PlatformRequestError("Local app bridge required.", 400, "local_app_required");
      }
      const chat = clone(ctx.getChat());
      if (chat.behavior && chat.behavior.behaviorId === "novel_theater") {
        chat.behavior = {
          ...chat.behavior,
          stateVersion: chat.behavior.stateVersion + 1,
          hud: { ...(chat.behavior.hud ?? {}), chapterIndex: input.chapterIndex },
        };
        ctx.setChat(chat);
      }
      return delay({ ok: true, chat }, 40);
    },
  };
}
