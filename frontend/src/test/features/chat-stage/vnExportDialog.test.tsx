import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VnExportDialog } from "../../../features/chat-stage/replay/VnExportDialog";
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
});
