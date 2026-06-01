import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BackgroundMusicSection } from "../../../features/background-manager/BackgroundMusicSection";
import { BackgroundSpriteGallery } from "../../../features/background-manager/BackgroundSpriteGallery";
import { BackgroundTagsDialog } from "../../../features/background-manager/BackgroundTagsDialog";
import type { BackgroundBgmItem } from "../../../features/background-manager/backgroundUtils";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderEn(children: ReactNode) {
  return render(<I18nProvider language="en">{children}</I18nProvider>);
}

const bgmItems: BackgroundBgmItem[] = [
  { filename: "intro.mp3", originalIndex: 0, path: "/project/assets/bgm/intro.mp3" },
  { filename: "ending.ogg", originalIndex: 1, path: "/project/assets/bgm/ending.ogg" },
];

describe("Background management sections", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("edits and confirms background batch tag dialogs", () => {
    const onChange = vi.fn();
    const onClose = vi.fn();
    const onConfirm = vi.fn();

    renderEn(
      <BackgroundTagsDialog
        draft="night\nrain"
        fieldLabel="Image tags"
        help="One tag per line."
        onChange={onChange}
        onClose={onClose}
        onConfirm={onConfirm}
        open
        title="Batch image tags"
      />,
    );

    expect(screen.getByRole("dialog", { name: "Batch image tags" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Image tags"), { target: { value: "dawn" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onChange).toHaveBeenCalledWith("dawn");
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders background images with selected preview and edit actions", () => {
    const onDeleteImage = vi.fn();
    const onSelectImage = vi.fn();
    const onUpdateImageTag = vi.fn();
    const onSaveImageTags = vi.fn();
    const onOpenBulkTags = vi.fn();
    const onClearImages = vi.fn();

    renderEn(
      <BackgroundSpriteGallery
        currentBackgroundName="school"
        deletePending={false}
        imageRowTags={["night", "day"]}
        onClearImages={onClearImages}
        onDeleteImage={onDeleteImage}
        onOpenBulkTags={onOpenBulkTags}
        onSaveImageTags={onSaveImageTags}
        onSelectImage={onSelectImage}
        onUpdateImageTag={onUpdateImageTag}
        onUploadImages={vi.fn()}
        saveTagsPending={false}
        selectedImageIndex={0}
        sprites={[{ path: "/project/bg/school-night.webp" }, { path: "/project/bg/school-day.webp" }]}
        uploadPending={false}
      />,
    );

    expect(screen.getByRole("heading", { name: "Background images" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /school-night.webp/ })).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("button", { name: /school-day.webp/ }));
    fireEvent.change(screen.getByLabelText("Tag"), { target: { value: "storm" } });
    fireEvent.click(screen.getByRole("button", { name: "Save image description" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Batch image tags" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete all images" }));

    expect(onSelectImage).toHaveBeenCalledWith(1);
    expect(onUpdateImageTag).toHaveBeenCalledWith(0, "storm");
    expect(onSaveImageTags).toHaveBeenCalledTimes(1);
    expect(onDeleteImage).toHaveBeenCalledWith(0);
    expect(onOpenBulkTags).toHaveBeenCalledTimes(1);
    expect(onClearImages).toHaveBeenCalledTimes(1);
  });

  it("keeps BGM table controls wired for selection, sorting, tag edits, and deletes", () => {
    const onBatchDelete = vi.fn();
    const onClearAll = vi.fn();
    const onDelete = vi.fn();
    const onOpenBulkTags = vi.fn();
    const onSortToggle = vi.fn();
    const onTagChange = vi.fn();
    const onToggleAllSelection = vi.fn();
    const onToggleSelection = vi.fn();

    renderEn(
      <BackgroundMusicSection
        batchDeletePending={false}
        bgmList={bgmItems.map((item) => item.path)}
        bgmRowTags={["calm", "ending"]}
        currentBackgroundName="school"
        deletePending={false}
        onBatchDelete={onBatchDelete}
        onClearAll={onClearAll}
        onDelete={onDelete}
        onOpenBulkTags={onOpenBulkTags}
        onSortToggle={onSortToggle}
        onTagChange={onTagChange}
        onToggleAllSelection={onToggleAllSelection}
        onToggleSelection={onToggleSelection}
        onUpload={vi.fn()}
        selectedBgmIndexSet={new Set([1])}
        sortDirection="asc"
        sortKey="index"
        sortedBgmItems={bgmItems}
        uploadPending={false}
      />,
    );

    expect(screen.getByRole("heading", { name: "Background music" })).toBeInTheDocument();
    expect(screen.getAllByText("intro.mp3").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Select all BGM" })).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: "Select all BGM" }));
    fireEvent.click(screen.getByRole("button", { name: "Index ascending" }));
    fireEvent.click(screen.getByRole("button", { name: "File name" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select 1" }));
    fireEvent.change(screen.getAllByLabelText("Tag")[0], { target: { value: "battle" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove intro.mp3" }));
    fireEvent.click(screen.getByRole("button", { name: "Batch BGM tags" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected BGM" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete all BGM" }));

    expect(onToggleAllSelection).toHaveBeenCalledTimes(1);
    expect(onSortToggle).toHaveBeenCalledWith("index");
    expect(onSortToggle).toHaveBeenCalledWith("filename");
    expect(onToggleSelection).toHaveBeenCalledWith(0, true);
    expect(onTagChange).toHaveBeenCalledWith(0, "battle");
    expect(onDelete).toHaveBeenCalledWith(0);
    expect(onOpenBulkTags).toHaveBeenCalledTimes(1);
    expect(onBatchDelete).toHaveBeenCalledTimes(1);
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });
});
