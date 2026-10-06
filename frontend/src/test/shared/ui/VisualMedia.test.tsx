import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isMp4Media } from "../../../shared/assets/visualMedia";
import { VisualMedia } from "../../../shared/ui/VisualMedia";
import { ImageAssetGallery } from "../../../shared/ui/ImageAssetGallery";
import { CharacterVisual } from "../../../modules/character-visual/CharacterVisual";
import { BackgroundLayer, SpriteLayer } from "../../../features/chat-stage/components/StageLayers";

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `/api/media?path=${encodeURIComponent(path)}&token=test`,
}));

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("file-based visual media", () => {
  it.each([
    "C:\\sprites\\happy.MP4",
    "/clip.mp4?cache=2",
    "/api/media?path=data%2Fsprite%2Fhappy.MP4&token=test",
    "https://cdn.example/clip.mp4?path=other",
    "data:video/mp4;base64,AAAA",
  ])("recognizes MP4 before playback: %s", (source) => expect(isMp4Media(source)).toBe(true));

  it.each(["/happy.gif", "/api/media?path=happy.png&token=.mp4", "data:image/png;base64,AAAA", "blob:clip.mp4"])(
    "keeps other visuals on the image path: %s",
    (source) => expect(isMp4Media(source)).toBe(false),
  );

  it("preserves GIF rendering, dimensions and mouse interaction", () => {
    const onDimensions = vi.fn(),
      onMouseDown = vi.fn();
    render(<VisualMedia alt="happy" src="/happy.gif" onDimensions={onDimensions} onMouseDown={onMouseDown} />);
    const image = screen.getByRole("img") as HTMLImageElement;
    Object.defineProperties(image, { naturalWidth: { value: 320 }, naturalHeight: { value: 640 } });
    fireEvent.load(image);
    fireEvent.mouseDown(image);
    expect(onDimensions).toHaveBeenCalledWith(320, 640);
    expect(onMouseDown).toHaveBeenCalledOnce();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("loops silently, pauses when hidden and resumes without restarting the source", () => {
    const view = render(<VisualMedia alt="happy" src="/happy.mp4" />);
    const video = screen.getByLabelText("happy") as HTMLVideoElement;
    expect(video.muted).toBe(true);
    expect(video.loop).toBe(true);
    expect(video.playsInline).toBe(true);
    expect(video.controls).toBe(false);
    expect(video.play).toHaveBeenCalledOnce();
    const loads = vi.mocked(video.load).mock.calls.length;
    view.rerender(<VisualMedia alt="happy" src="/happy.mp4" active={false} />);
    expect(video.autoplay).toBe(false);
    expect(video.pause).toHaveBeenCalled();
    view.rerender(<VisualMedia alt="happy" src="/happy.mp4" />);
    expect(video.play).toHaveBeenCalledTimes(2);
    expect(video.load).toHaveBeenCalledTimes(loads);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    fireEvent(document, new Event("visibilitychange"));
    expect(video.autoplay).toBe(false);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    fireEvent(document, new Event("visibilitychange"));
    expect(video.autoplay).toBe(true);
    expect(video.load).toHaveBeenCalledTimes(loads);
  });

  it("releases old videos and ignores autoplay failure when switching to an image", async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValue(new DOMException("blocked", "NotAllowedError"));
    const view = render(<VisualMedia alt="happy" src="/happy.mp4" />);
    const old = screen.getByLabelText("happy");
    await act(async () => {});
    view.rerender(<VisualMedia alt="sad" src="/sad.png" />);
    expect(old).not.toHaveAttribute("src");
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(screen.getByRole("img")).toHaveAttribute("src", "/sad.png");
  });

  it("shows a useful preview error and releases the failed source", () => {
    const view = render(<VisualMedia alt="broken" errorMessage="Check the H.264 MP4 file." src="/broken.mp4" />);
    const video = screen.getByLabelText("broken");
    fireEvent.error(video);
    expect(screen.getByRole("status")).toHaveTextContent("H.264");
    expect(video).not.toHaveAttribute("src");
    view.rerender(<VisualMedia alt="valid" src="/valid.mp4" />);
    expect(screen.getByLabelText("valid")).toHaveAttribute("src", "/valid.mp4");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("pauses a late play result after the layer is hidden", async () => {
    let complete!: () => void;
    vi.mocked(HTMLMediaElement.prototype.play).mockReturnValue(
      new Promise<void>((resolve) => {
        complete = resolve;
      }),
    );
    const view = render(<VisualMedia alt="happy" src="/happy.mp4" />);
    view.rerender(<VisualMedia alt="happy" src="/happy.mp4" active={false} />);
    const paused = vi.mocked(HTMLMediaElement.prototype.pause).mock.calls.length;
    await act(async () => complete());
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(paused + 1);
  });

  it("restores its source after StrictMode effect replay", () => {
    render(
      <StrictMode>
        <VisualMedia alt="happy" src="/happy.mp4" />
      </StrictMode>,
    );
    expect(screen.getByLabelText("happy")).toHaveAttribute("src", "/happy.mp4");
  });

  it("loads a paused cover only when the gallery thumbnail enters view", () => {
    let intersect!: (entries: { isIntersecting: boolean }[]) => void;
    const disconnect = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: typeof intersect) {
          intersect = callback;
        }
        observe = vi.fn();
        disconnect = disconnect;
      },
    );
    const view = render(
      <ImageAssetGallery
        items={[{ id: "video", title: "happy.mp4", videoSrc: "/happy.mp4" }]}
        selectedIndex={0}
        onSelect={() => {}}
      />,
    );
    const video = view.container.querySelector("video")!;
    expect(video).not.toHaveAttribute("src");
    act(() => intersect([{ isIntersecting: true }]));
    expect(video).toHaveAttribute("src", "/happy.mp4");
    expect(video.play).not.toHaveBeenCalled();
    Object.defineProperty(video, "duration", { value: 2 });
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(0.001);
    fireEvent.loadedData(video);
    expect(video.closest(".image-asset-card__media")).toHaveAttribute("data-state", "loaded");
    act(() => intersect([{ isIntersecting: false }]));
    expect(video).not.toHaveAttribute("src");
    act(() => intersect([{ isIntersecting: true }]));
    expect(video).toHaveAttribute("src", "/happy.mp4");
    expect(video.play).not.toHaveBeenCalled();
    fireEvent.error(video);
    expect(video.closest(".image-asset-card__media")).toHaveAttribute("data-state", "error");
    view.unmount();
    expect(disconnect).toHaveBeenCalled();
  });

  it("uses video dimensions for framed sprites and preserves dragging and error handling", () => {
    const onMouseDown = vi.fn(),
      onImageError = vi.fn();
    const view = render(
      <CharacterVisual
        asset={{ id: "happy", label: "happy", avatarType: "static", modelUrl: "", url: "/happy.mp4" }}
        className="sprite-layer__image"
        framing={{ heightRatio: 0.5, verticalPosition: 0 }}
        hitbox
        mode="play"
        onMouseDown={onMouseDown}
        onImageError={onImageError}
      />,
    );
    const video = screen.getByLabelText("happy") as HTMLVideoElement;
    Object.defineProperties(video, { videoWidth: { value: 360 }, videoHeight: { value: 720 } });
    fireEvent.loadedMetadata(video);
    expect(view.container.querySelector<HTMLElement>(".character-visual__static-frame")!.style.aspectRatio).toBe("0.5");
    expect(video.parentElement).toHaveStyle({ transform: "translateY(0%) scale(2)" });
    fireEvent.mouseDown(video);
    fireEvent.error(video);
    expect(onMouseDown).toHaveBeenCalledOnce();
    expect(onImageError).toHaveBeenCalledOnce();
  });

  it("propagates stage visibility to both video sprites and backgrounds", () => {
    const stage = (hidden: boolean) => (
      <>
        <BackgroundLayer hidden={hidden} path="data/backgrounds/rain.mp4" transparent={false} />
        <SpriteLayer
          hidden={hidden}
          sprites={[
            { id: "alice", label: "Alice", avatarType: "static", modelUrl: "", path: "data/sprite/alice/happy.mp4" },
          ]}
          runtimeScaleForSprite={() => 1}
        />
      </>
    );
    const view = render(stage(false));
    const videos = [...view.container.querySelectorAll("video")];
    expect(videos).toHaveLength(2);
    expect(videos.every((video) => video.autoplay && video.muted)).toBe(true);
    fireEvent.error(videos[0]);
    expect(videos[0].dataset.loadState).toBe("error");
    view.rerender(stage(true));
    expect(videos.every((video) => !video.autoplay)).toBe(true);
  });
});
