import { fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { BackgroundMusicSection } from "../../../features/background-manager/BackgroundMusicSection";
import type { BackgroundBgmItem } from "../../../features/background-manager/backgroundUtils";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

let originalMediaLoad: PropertyDescriptor | undefined;
let originalMediaPause: PropertyDescriptor | undefined;

beforeAll(() => {
  originalMediaLoad = Object.getOwnPropertyDescriptor(window.HTMLMediaElement.prototype, "load");
  originalMediaPause = Object.getOwnPropertyDescriptor(window.HTMLMediaElement.prototype, "pause");
  Object.defineProperty(window.HTMLMediaElement.prototype, "load", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(window.HTMLMediaElement.prototype, "pause", {
    configurable: true,
    value: vi.fn(),
  });
});

afterAll(() => {
  if (originalMediaLoad) {
    Object.defineProperty(window.HTMLMediaElement.prototype, "load", originalMediaLoad);
  }
  if (originalMediaPause) {
    Object.defineProperty(window.HTMLMediaElement.prototype, "pause", originalMediaPause);
  }
});

function renderSection(overrides: Partial<Parameters<typeof BackgroundMusicSection>[0]> = {}) {
  const props: Parameters<typeof BackgroundMusicSection>[0] = {
    batchDeletePending: false,
    bgmList: ["D:/bgm/track-10.mp3", "D:/bgm/track-2.mp3", "D:/bgm/ambient.mp3"],
    bgmRowTags: ["tense", "active", "calm"],
    currentBackgroundName: "school",
    deletePending: false,
    onBatchDelete: vi.fn(),
    onClearAll: vi.fn(),
    onDelete: vi.fn(),
    onOpenBulkTags: vi.fn(),
    onSortToggle: vi.fn(),
    onTagChange: vi.fn(),
    onToggleAllSelection: vi.fn(),
    onToggleSelection: vi.fn(),
    onUpload: vi.fn(),
    selectedBgmIndexSet: new Set<number>(),
    sortDirection: "asc",
    sortKey: "filename",
    sortedBgmItems: [
      { filename: "ambient.mp3", originalIndex: 2, path: "D:/bgm/ambient.mp3" },
      { filename: "track-2.mp3", originalIndex: 1, path: "D:/bgm/track-2.mp3" },
      { filename: "track-10.mp3", originalIndex: 0, path: "D:/bgm/track-10.mp3" },
    ] satisfies BackgroundBgmItem[],
    uploadPending: false,
  };

  const result = render(
    <I18nProvider language="en">
      <BackgroundMusicSection {...props} {...overrides} />
    </I18nProvider>,
  );

  return { props: { ...props, ...overrides }, ...result };
}

describe("BackgroundMusicSection", () => {
  it("renders sorted BGM rows while preserving original row indexes for actions", () => {
    const { props } = renderSection();

    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("ambient.mp3");
    expect(rows[1]).toHaveTextContent("track-2.mp3");
    expect(rows[2]).toHaveTextContent("track-10.mp3");

    fireEvent.click(screen.getByLabelText("Select 3"));
    expect(props.onToggleSelection).toHaveBeenCalledWith(2, true);

    fireEvent.change(screen.getAllByLabelText("Tag")[0], { target: { value: "quiet" } });
    expect(props.onTagChange).toHaveBeenCalledWith(2, "quiet");

    fireEvent.click(screen.getByLabelText("Remove ambient.mp3"));
    expect(props.onDelete).toHaveBeenCalledWith(2);
  });

  it("routes toolbar actions through public callbacks", () => {
    const { props } = renderSection({
      selectedBgmIndexSet: new Set([1]),
    });

    fireEvent.click(screen.getByRole("button", { name: "Upload BGM" }));
    expect(screen.getByRole("dialog", { name: "Select BGM files" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Batch BGM tags" }));
    expect(props.onOpenBulkTags).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Delete selected BGM" }));
    expect(props.onBatchDelete).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Delete all BGM" }));
    expect(props.onClearAll).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "File name ascending" }));
    expect(props.onSortToggle).toHaveBeenCalledWith("filename");

    fireEvent.click(screen.getByRole("button", { name: "Select all BGM" }));
    expect(props.onToggleAllSelection).toHaveBeenCalledTimes(1);
  });

  it("disables destructive and upload actions when no background context exists", () => {
    renderSection({
      currentBackgroundName: "",
      selectedBgmIndexSet: new Set([1]),
    });

    expect(screen.getByRole("button", { name: "Upload BGM" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete selected BGM" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete all BGM" })).toBeDisabled();
  });
});
