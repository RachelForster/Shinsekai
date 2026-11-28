import type { ChatLaunchPayload, ChatSnapshot, ConversationSummary } from "./chatTypes";

export interface NovelDocumentManifest {
  docId: string;
  title: string;
  sourceFormat: string;
  sourceFilename: string;
  totalChars: number;
  totalChunks: number;
  totalChapters: number;
  createdAtMs: number;
  pageCount: number | null;
  chunkConfig: Record<string, number>;
}

export interface NovelChapterTocEntry {
  index: number;
  title: string;
  startChunkIndex: number;
  chunkCount: number;
  pageStart: number | null;
  pageEnd: number | null;
}

export interface NovelSampleChunk {
  chunkId: string;
  index: number;
  chapterIndex: number;
  text: string;
}

export interface NovelDocumentSummary {
  manifest: NovelDocumentManifest;
  chapters: NovelChapterTocEntry[];
}

export interface NovelDocumentDetail extends NovelDocumentSummary {
  sampleChunks: NovelSampleChunk[];
}

export type NovelCastRole = "protagonist" | "supporting" | "antagonist";

export type NovelNameMode = "actor" | "story";

export interface NovelCastCandidate {
  name: string;
  aliases: string[];
  role: NovelCastRole;
  description: string;
  isFirstPerson: boolean;
  suggestedCharacter: string;
}

export interface NovelAvailableCharacter {
  name: string;
  brief: string;
}

export interface NovelCastExtractionResult {
  docId: string;
  characters: NovelCastCandidate[];
  availableCharacters: NovelAvailableCharacter[];
}

export interface NovelCastBindingInput {
  sourceName: string;
  aliases?: string[];
  targetCharacter?: string;
  role?: NovelCastRole;
  silhouetteUntilRevealed?: boolean;
}

export interface NovelLaunchRequest {
  docId: string;
  casting?: NovelCastBindingInput[];
  nameMode?: NovelNameMode;
  startChapterIndex?: number;
  backgroundName?: string;
  conversationTitle?: string;
  mediaSelectionMode?: "indexed" | "semantic";
  useEffect?: boolean;
  useTranslation?: boolean;
  enableMobileAccess?: boolean;
  historyPath?: string;
}

export interface NovelJumpChapterInput {
  chapterIndex: number;
  expectedStateVersion: number;
  commandId?: string;
}

export interface NovelPlatform {
  listDocuments: () => Promise<NovelDocumentSummary[]>;
  importDocument: (file: File) => Promise<NovelDocumentDetail>;
  getDocument: (docId: string) => Promise<NovelDocumentDetail>;
  deleteDocument: (docId: string) => Promise<{ ok: boolean; docId: string }>;
  extractCast: (docId: string) => Promise<NovelCastExtractionResult>;
  saveCasting: (
    conversationId: string,
    bindings: NovelCastBindingInput[],
    nameMode?: NovelNameMode,
  ) => Promise<ConversationSummary>;
  prepareLaunchPayload: (input: NovelLaunchRequest) => Promise<ChatLaunchPayload>;
  jumpChapter: (input: NovelJumpChapterInput) => Promise<{ ok: boolean; chat: ChatSnapshot }>;
}
