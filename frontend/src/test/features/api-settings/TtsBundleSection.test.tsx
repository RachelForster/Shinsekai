import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TtsBundleSection } from "../../../features/api-settings/TtsBundleSection";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { TaskSnapshot, TtsBundleDownloadResult } from "../../../shared/platform/types";

function task(): TaskSnapshot<TtsBundleDownloadResult> {
  return {
    createdAt: 0,
    id: "download-1",
    kind: "tts-bundle",
    logs: ["Downloading"],
    message: "Downloading",
    phase: "download",
    status: "running",
    title: "TTS bundle",
    updatedAt: 0,
  };
}

function renderSection(overrides: Partial<Parameters<typeof TtsBundleSection>[0]> = {}) {
  const props: Parameters<typeof TtsBundleSection>[0] = {
    canCancelDownload: false,
    cancelPending: false,
    dialogOpen: false,
    downloadPending: false,
    error: null,
    kind: "genie",
    onCancelDownload: vi.fn(),
    onCloseDialog: vi.fn(),
    onKindChange: vi.fn(),
    onOpenDialog: vi.fn(),
    onStartDownload: vi.fn(),
    recommendation: {
      gpus: [{ device: "RTX 4090", vendor: "NVIDIA", vram_gb: 24 }],
      kind: "gptso",
      platform: "Windows",
    },
    recommendationError: false,
    recommendationLoading: false,
    savePending: false,
    task: null,
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <TtsBundleSection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("TtsBundleSection", () => {
  it("opens the download dialog from the section action", () => {
    const { props } = renderSection();

    fireEvent.click(screen.getByRole("button", { name: "Choose package" }));
    expect(props.onOpenDialog).toHaveBeenCalledTimes(1);
  });

  it("renders recommendation, task progress, and dialog actions", () => {
    const { props } = renderSection({
      canCancelDownload: true,
      dialogOpen: true,
      error: "Download failed",
      task: task(),
    });
    const dialog = screen.getByRole("dialog", { name: "Download TTS package" });

    expect(within(dialog).getByText("Windows")).toBeInTheDocument();
    expect(within(dialog).getByText("NVIDIA RTX 4090 / 24 GB")).toBeInTheDocument();
    expect(within(dialog).getAllByText("GPT-SoVITS v2pro").length).toBeGreaterThan(0);
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Download failed");
    expect(within(dialog).getByText("Downloading")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "GPT-SoVITS v2pro for RTX 50" }));
    expect(props.onKindChange).toHaveBeenCalledWith("gptso50");

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel download" }));
    expect(props.onCancelDownload).toHaveBeenCalledTimes(1);

    fireEvent.click(within(dialog).getByRole("button", { name: "Start download" }));
    expect(props.onStartDownload).toHaveBeenCalledTimes(1);

    fireEvent.click(within(dialog).getAllByRole("button", { name: "Close" })[0]);
    expect(props.onCloseDialog).toHaveBeenCalledTimes(1);
  });
});
