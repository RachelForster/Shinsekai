import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NovelChapterDrawer } from "../../../features/chat-stage/components/NovelChapterDrawer";
import { I18nProvider } from "../../../shared/i18n";
import type { ChatBehaviorState } from "../../../shared/platform/types";

const getNovelDocument = vi.hoisted(() => vi.fn());

vi.mock("../../../entities/novel/repository", () => ({
  getNovelDocument,
}));

function makeBehavior(overrides: Partial<ChatBehaviorState> = {}): ChatBehaviorState {
  return {
    behaviorId: "novel_theater",
    stateVersion: 4,
    stagePolicy: {
      hideInputLayer: true,
      playbackEndAction: "auto_advance",
      allowFreeTextInterject: false,
      allowUnboundSpeakers: true,
    },
    hud: {
      docId: "doc-1",
      title: "Lantern Harbor",
      chapterIndex: 1,
      totalChapters: 3,
      chunkIndex: 3,
      totalChunks: 12,
      phase: "playing",
      chapters: [
        { index: 0, title: "Ch 1", startChunkIndex: 0, chunkCount: 3, pageStart: null, pageEnd: null },
        { index: 1, title: "Ch 2", startChunkIndex: 3, chunkCount: 4, pageStart: null, pageEnd: null },
        { index: 2, title: "Ch 3", startChunkIndex: 7, chunkCount: 5, pageStart: null, pageEnd: null },
      ],
      chaptersTruncated: false,
    },
    ...overrides,
  };
}

describe("NovelChapterDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("displays current chapter progress and triggers chapter jump callback", () => {
    const onSelectChapter = vi.fn();
    render(
      <I18nProvider language="en">
        <NovelChapterDrawer behavior={makeBehavior()} onClose={vi.fn()} onSelectChapter={onSelectChapter} open />
      </I18nProvider>,
    );

    expect(screen.getByText("Ch. 2 · 4/12")).toBeVisible();
    expect(screen.getByText("Current")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /Ch 3/ }));
    expect(onSelectChapter).toHaveBeenCalledWith(2);
    expect(getNovelDocument).not.toHaveBeenCalled();
  });

  it("lazy-fetches full TOC via getNovelDocument when chaptersTruncated is true", async () => {
    getNovelDocument.mockResolvedValue({
      manifest: { docId: "doc-1" },
      chapters: [
        { index: 0, title: "Full Chapter 1", startChunkIndex: 0, chunkCount: 2, pageStart: null, pageEnd: null },
        { index: 501, title: "Full Chapter 502", startChunkIndex: 900, chunkCount: 2, pageStart: null, pageEnd: null },
      ],
      sampleChunks: [],
    });

    const truncated = makeBehavior({
      hud: {
        docId: "doc-1",
        title: "Long Book",
        chapterIndex: 0,
        totalChapters: 502,
        chunkIndex: 0,
        totalChunks: 902,
        phase: "playing",
        chapters: [
          { index: 0, title: "Partial Ch 1", startChunkIndex: 0, chunkCount: 2, pageStart: null, pageEnd: null },
        ],
        chaptersTruncated: true,
      },
    });

    render(
      <I18nProvider language="en">
        <NovelChapterDrawer behavior={truncated} onClose={vi.fn()} onSelectChapter={vi.fn()} open />
      </I18nProvider>,
    );

    await waitFor(() => expect(getNovelDocument).toHaveBeenCalledWith("doc-1"));
    expect(await screen.findByText("Full Chapter 502")).toBeVisible();
  });
});
