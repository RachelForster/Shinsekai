import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BackgroundSpriteGallery } from "../../../features/background-manager/BackgroundSpriteGallery";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const filesRepositoryMock = vi.hoisted(() => ({
  fileThumbnailBatch: vi.fn(
    (
      paths: string[],
      size?: number,
      options?: { batchSize?: number; delivery?: "data" | "url"; onBatch?: (sources: Record<string, string>) => void },
    ) => {
      const delivery = options?.delivery ?? "url";
      const sources = Object.fromEntries(paths.map((path) => [path, `${delivery}://thumb/${size ?? 0}/${path}`]));
      options?.onBatch?.(sources);
      return Promise.resolve(sources);
    },
  ),
}));

vi.mock("../../../entities/files/repository", () => ({
  fileThumbnailBatch: filesRepositoryMock.fileThumbnailBatch,
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
  beforeEach(() => {
    filesRepositoryMock.fileThumbnailBatch.mockClear();
  });

  it("only shows the smart-label action when vision is available", async () => {
    const onAutoLabel = vi.fn();
    const first = renderGallery();
    expect(screen.queryByRole("button", { name: "Smart labeling" })).not.toBeInTheDocument();
    first.unmount();

    renderGallery({ autoLabelAvailable: true, autoLabelDisabled: false, onAutoLabel });
    await waitFor(() => expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Smart labeling" }));
    expect(onAutoLabel).toHaveBeenCalledOnce();
  });

  it("shows empty image state and disables actions without a background context", () => {
    renderGallery({
      currentBackgroundName: "",
      sprites: [],
    });

    expect(screen.getByRole("button", { name: "Upload images / videos" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete all images" })).toBeDisabled();
  });

  it("routes selected image inspection actions by the selected sprite index", async () => {
    const { container, props } = renderGallery();

    expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalledWith(
      ["D:/bg/scene-a.png", "D:/bg/scene-b.png"],
      160,
      expect.objectContaining({
        batchSize: 128,
        delivery: "url",
        onBatch: expect.any(Function),
      }),
    );
    await waitFor(() => {
      expect(container.querySelectorAll('img[src^="url://thumb"]').length).toBe(2);
    });

    fireEvent.click(screen.getByRole("button", { name: /scene-a\.png/ }));
    expect(props.onSelectImage).toHaveBeenCalledWith(0);

    expect(screen.getByTitle("D:/bg/scene-b.png")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Tag"), { target: { value: "rainy night" } });
    expect(props.onUpdateImageTag).toHaveBeenCalledWith(1, "rainy night");

    fireEvent.click(screen.getByRole("button", { name: "Save image description" }));
    expect(props.onSaveImageTags).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(props.onDeleteImage).toHaveBeenCalledWith(1);

    fireEvent.click(screen.getByRole("button", { name: "Upload images / videos" }));
    expect(screen.getByRole("dialog", { name: "Select images or MP4 videos" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Batch image tags" }));
    expect(props.onOpenBulkTags).toHaveBeenCalledTimes(1);
  });

  it("previews MP4 backgrounds without sending them to the image thumbnail service", async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    const load = vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    const view = renderGallery({
      sprites: [{ path: "D:/bg/day.png" }, { path: "D:/bg/rain.mp4" }],
      selectedImageIndex: 1,
    });
    await waitFor(() => expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalledOnce());
    expect(filesRepositoryMock.fileThumbnailBatch.mock.calls[0][0]).toEqual(["D:/bg/day.png"]);
    const preview = view.container.querySelector<HTMLVideoElement>(".asset-inspector__preview video")!;
    const cover = view.container.querySelector<HTMLVideoElement>(".image-asset-card video")!;
    expect(preview).toHaveAttribute("src", "asset://D:/bg/rain.mp4");
    expect(preview.autoplay).toBe(true);
    expect(cover.autoplay).toBe(false);
    expect(play).toHaveBeenCalledOnce();
    view.unmount();
    play.mockRestore();
    pause.mockRestore();
    load.mockRestore();
  });

  it("keeps loaded thumbnails when parent rerenders with the same sprite paths", async () => {
    const { container, props, rerender } = renderGallery();

    await waitFor(() => {
      expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalledTimes(1);
    });

    rerender(
      <I18nProvider language="en">
        <BackgroundSpriteGallery
          {...props}
          imageRowTags={["day", "dusk"]}
          sprites={[{ path: "D:/bg/scene-a.png" }, { path: "D:/bg/scene-b.png" }]}
        />
      </I18nProvider>,
    );

    expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalledTimes(1);
    expect(container.querySelectorAll('img[src^="url://thumb"]').length).toBe(2);
  });

  it("preheats background thumbnails through cache URL batches", async () => {
    const sprites = Array.from({ length: 30 }, (_, index) => ({ path: `D:/bg/scene-${index}.png` }));
    renderGallery({
      imageRowTags: sprites.map(() => ""),
      sprites,
    });

    await waitFor(() => {
      expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalledTimes(1);
    });
    expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalledWith(
      sprites.map((sprite) => sprite.path),
      160,
      expect.objectContaining({
        batchSize: 128,
        delivery: "url",
        onBatch: expect.any(Function),
      }),
    );
  });

  it("renders large background image lists in batches", async () => {
    const sprites = Array.from({ length: 130 }, (_, index) => ({ path: `D:/bg/scene-${index}.png` }));
    const { container } = renderGallery({
      imageRowTags: sprites.map(() => ""),
      sprites,
    });

    await waitFor(() => {
      expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalledTimes(1);
    });
    expect(container.querySelectorAll(".image-asset-card")).toHaveLength(96);
    expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenLastCalledWith(
      sprites.slice(0, 96).map((sprite) => sprite.path),
      160,
      expect.objectContaining({
        batchSize: 128,
        delivery: "url",
        onBatch: expect.any(Function),
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Show more images (96/130)" }));

    await waitFor(() => {
      expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenCalledTimes(2);
    });
    expect(container.querySelectorAll(".image-asset-card")).toHaveLength(130);
    expect(filesRepositoryMock.fileThumbnailBatch).toHaveBeenLastCalledWith(
      sprites.map((sprite) => sprite.path),
      160,
      expect.objectContaining({
        batchSize: 128,
        delivery: "url",
        onBatch: expect.any(Function),
      }),
    );
  });
});
