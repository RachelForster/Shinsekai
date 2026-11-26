import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VnExportDialog } from "../../../features/chat-stage/replay/VnExportDialog";
import { HistoryDialog } from "../../../features/chat-stage/components/HistoryDialog";
import * as chatRepo from "../../../entities/chat/repository";
import { I18nProvider } from "../../../shared/i18n";

vi.mock("../../../entities/chat/repository", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../entities/chat/repository")>();
  return {
    ...actual,
    exportPlayableVn: vi.fn(),
  };
});

describe("VnExportDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("submits ZIP export options and renders stats, warnings, and download link", async () => {
    vi.mocked(chatRepo.exportPlayableVn).mockResolvedValue({
      path: "output/vn_exports/story.zip",
      format: "zip",
      entryCount: 12,
      assetCount: 4,
      voiceCount: 5,
      transcodedVoiceCount: 5,
      skippedNonStaticSprites: 1,
      totalBytes: 245760,
      indexHtmlBytes: 2400,
      warnings: ["skipped_non_static_sprites"],
      downloadUrl: "http://127.0.0.1:8765/api/download?path=output/vn_exports/story.zip",
    });

    render(
      <I18nProvider language="en">
        <VnExportDialog conversationId="conv-1" defaultTitle="Starry Night" onClose={vi.fn()} open rangeCount={12} />
      </I18nProvider>,
    );

    expect(screen.getByDisplayValue("Starry Night")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Export VN" }));

    await waitFor(() => {
      expect(screen.getByText("Visual novel package ready")).toBeInTheDocument();
    });

    expect(chatRepo.exportPlayableVn).toHaveBeenCalledWith({
      conversationId: "conv-1",
      title: "Starry Night",
      subtitle: "",
      outputFormat: "zip",
      outputDir: "",
      includeVoices: true,
      transcodeMp3: true,
      includeBgm: true,
      includeAmbient: true,
      userDisplayName: "",
      openFolder: false,
    });
    expect(screen.getByRole("link", { name: "Download ZIP" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8765/api/download?path=output/vn_exports/story.zip",
    );
    expect(screen.getByText(/skipped 1 Live2D\/MMD/i)).toBeInTheDocument();
  });

  it("switches to directory mode and disables transcoding when voices are disabled", async () => {
    vi.mocked(chatRepo.exportPlayableVn).mockResolvedValue({
      path: "D:/Exports/vn-dir",
      format: "directory",
      entryCount: 3,
      assetCount: 1,
      voiceCount: 0,
      transcodedVoiceCount: 0,
      skippedNonStaticSprites: 0,
      totalBytes: 4096,
      indexHtmlBytes: 2048,
      warnings: [],
    });

    render(
      <I18nProvider language="en">
        <VnExportDialog defaultUserDisplayName="Traveler" endEntryId="h-3" onClose={vi.fn()} open startEntryId="h-1" />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByLabelText(/Standalone folder/i));
    fireEvent.click(screen.getByLabelText(/Include archived voice lines/i));
    fireEvent.click(screen.getByRole("button", { name: "Export VN" }));

    await waitFor(() => {
      expect(screen.getByText("D:/Exports/vn-dir")).toBeInTheDocument();
    });

    expect(chatRepo.exportPlayableVn).toHaveBeenCalledWith(
      expect.objectContaining({
        startEntryId: "h-1",
        endEntryId: "h-3",
        outputFormat: "directory",
        includeVoices: false,
        transcodeMp3: false,
        userDisplayName: "Traveler",
        openFolder: true,
      }),
    );
  });

  it("disables VN export for option-only selection and forwards exact anchors for non-contiguous rows", async () => {
    vi.mocked(chatRepo.exportPlayableVn).mockResolvedValue({
      path: "output/vn_exports/exact.zip",
      format: "zip",
      entryCount: 2,
      assetCount: 1,
      voiceCount: 0,
      transcodedVoiceCount: 0,
      skippedNonStaticSprites: 0,
      totalBytes: 2048,
      indexHtmlBytes: 1024,
      warnings: [],
    });

    render(
      <I18nProvider language="en">
        <HistoryDialog
          entries={[
            { id: "h-0", role: "assistant", dialogId: "d0", text: "Mio: Hello" },
            { id: "h-1", role: "options", text: "CHOICE: Opt A / Opt B" },
            { id: "h-2", role: "user", text: "You: Opt A", revertUserIndex: 0 },
          ]}
          loading={false}
          onClear={vi.fn()}
          onClose={vi.fn()}
          onExportImage={vi.fn()}
          onRefresh={vi.fn()}
          onReplayVoice={vi.fn()}
          onRevert={vi.fn()}
          onSaveVoice={vi.fn()}
          onToggleVoiceArchive={vi.fn()}
          open
          recordAudio={() => ({ start: vi.fn(), stop: vi.fn() }) as never}
          sessionId="sess-42"
          userDisplayName="Hero"
          voiceArchiveEnabled={false}
        />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Replay/Share" }));
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(3);

    // Selecting only the options row keeps Export playable VN disabled.
    fireEvent.click(checkboxes[1]!);
    expect(screen.getByRole("button", { name: "Export playable VN" })).toBeDisabled();

    // Adding first & third (playable) rows enables Export playable VN and sends exact IDs + session + anchors.
    fireEvent.click(checkboxes[0]!);
    fireEvent.click(checkboxes[2]!);
    const vnButton = screen.getByRole("button", { name: "Export playable VN" });
    expect(vnButton).toBeEnabled();
    fireEvent.click(vnButton);

    await waitFor(() => {
      expect(screen.getByText(/Exports 2 selected dialogue entries/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Export VN" }));
    await waitFor(() => {
      expect(chatRepo.exportPlayableVn).toHaveBeenCalledWith(
        expect.objectContaining({
          expectedSessionId: "sess-42",
          selectedEntryIds: ["h-0", "h-2"],
          selectedEntryAnchors: [
            { id: "h-0", role: "assistant", dialogId: "d0", text: "Mio: Hello" },
            { id: "h-2", role: "user", dialogId: "", text: "You: Opt A" },
          ],
        }),
      );
    });
  });

  it("keeps the frozen selection snapshot even when session or entries change while VnExportDialog is open", async () => {
    vi.mocked(chatRepo.exportPlayableVn).mockResolvedValue({
      path: "output/vn_exports/frozen.zip",
      format: "zip",
      entryCount: 2,
      assetCount: 0,
      voiceCount: 0,
      transcodedVoiceCount: 0,
      skippedNonStaticSprites: 0,
      totalBytes: 1024,
      indexHtmlBytes: 512,
      warnings: [],
    });

    const baseProps = {
      loading: false,
      onClear: vi.fn(),
      onClose: vi.fn(),
      onExportImage: vi.fn(),
      onRefresh: vi.fn(),
      onReplayVoice: vi.fn(),
      onRevert: vi.fn(),
      onSaveVoice: vi.fn(),
      onToggleVoiceArchive: vi.fn(),
      open: true,
      recordAudio: () => ({ start: vi.fn(), stop: vi.fn() }) as never,
      userDisplayName: "Hero",
      voiceArchiveEnabled: false,
    };

    const { rerender } = render(
      <I18nProvider language="en">
        <HistoryDialog
          {...baseProps}
          entries={[
            { id: "h-0", role: "assistant", dialogId: "d0", text: "Mio: Hello" },
            { id: "h-1", role: "user", text: "You: Reply", revertUserIndex: 0 },
          ]}
          sessionId="sess-42"
        />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Replay/Share" }));
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]!);
    fireEvent.click(checkboxes[1]!);
    fireEvent.click(screen.getByRole("button", { name: "Export playable VN" }));

    await waitFor(() => {
      expect(screen.getByText(/Exports 2 selected dialogue entries/i)).toBeInTheDocument();
    });

    rerender(
      <I18nProvider language="en">
        <HistoryDialog
          {...baseProps}
          entries={[{ id: "h-0", role: "assistant", dialogId: "d9", text: "Other: Switched" }]}
          sessionId="sess-99"
        />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Export VN" }));
    await waitFor(() => {
      expect(chatRepo.exportPlayableVn).toHaveBeenCalledWith(
        expect.objectContaining({
          expectedSessionId: "sess-42",
          selectedEntryIds: ["h-0", "h-1"],
          selectedEntryAnchors: [
            { id: "h-0", role: "assistant", dialogId: "d0", text: "Mio: Hello" },
            { id: "h-1", role: "user", dialogId: "", text: "You: Reply" },
          ],
        }),
      );
    });
  });
});
