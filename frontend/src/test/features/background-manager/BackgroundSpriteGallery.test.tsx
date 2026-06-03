import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BackgroundSpriteGallery } from "../../../features/background-manager/BackgroundSpriteGallery";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
  fileThumbnailUrl: (path: string, size?: number) => `thumb://${size ?? 0}/${path}`,
}));

function renderGallery(overrides: Partial<Parameters<typeof BackgroundSpriteGallery>[0]> = {}) {
  const props: Parameters<typeof BackgroundSpriteGallery>[0] = {
    currentBackgroundName: "school",
    deletePending: false,
    imageRowTags: ["day", "night"],
    onClearImages: vi.fn(),
    onDeleteImage: vi.fn(),
    onOpenBulkTags: vi.fn(),
    onSaveImageTags: vi.fn(),
    onSelectImage: vi.fn(),
    onUpdateImageTag: vi.fn(),
    onUploadImages: vi.fn(),
    saveTagsPending: false,
    selectedImageIndex: 1,
    sprites: [{ path: "D:/bg/scene-a.png" }, { path: "D:/bg/scene-b.png" }],
    uploadPending: false,
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <BackgroundSpriteGallery {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("BackgroundSpriteGallery", () => {
  it("shows empty image state and disables actions without a background context", () => {
    renderGallery({
      currentBackgroundName: "",
      sprites: [],
    });

    expect(screen.getByRole("button", { name: "Upload images" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete all images" })).toBeDisabled();
  });

  it("routes selected image inspection actions by the selected sprite index", () => {
    const { props } = renderGallery();

    fireEvent.click(screen.getByRole("button", { name: /scene-a\.png/ }));
    expect(props.onSelectImage).toHaveBeenCalledWith(0);

    expect(screen.getByTitle("D:/bg/scene-b.png")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Tag"), { target: { value: "rainy night" } });
    expect(props.onUpdateImageTag).toHaveBeenCalledWith(1, "rainy night");

    fireEvent.click(screen.getByRole("button", { name: "Save image description" }));
    expect(props.onSaveImageTags).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(props.onDeleteImage).toHaveBeenCalledWith(1);

    fireEvent.click(screen.getByRole("button", { name: "Upload images" }));
    expect(screen.getByRole("dialog", { name: "Select image files" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Batch image tags" }));
    expect(props.onOpenBulkTags).toHaveBeenCalledTimes(1);
  });
});
