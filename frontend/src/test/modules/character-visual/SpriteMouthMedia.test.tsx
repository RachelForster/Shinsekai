import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SpriteMouthMedia } from "../../../modules/character-visual/SpriteMouthMedia";
import { routeAvatarVoice } from "../../../modules/character-visual/voiceRoute";
import type { SpriteMouthManifest } from "../../../shared/assets/spriteMouth";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("loads JSON through the dedicated profile endpoint while preserving media authorization", async () => {
  const fetchProfile = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      version: 1,
      track: [{ time: 0, matrix: [1, 0, 0, 1, 0, 0] }],
      mouths: { closed: "mouth-closed.png", half: "mouth-half.png", open: "mouth-open.png" },
    }),
  });
  vi.stubGlobal("fetch", fetchProfile);
  render(
    <SpriteMouthMedia
      src="portrait.png"
      alt="Mika"
      mouthSync="http://localhost/api/media?path=data/sprite/mouth/manifest.json&shinsekai_bridge_token=secret"
    />,
  );
  await waitFor(() =>
    expect(fetchProfile).toHaveBeenCalledWith(
      "http://localhost/api/characters/sprites/mouth/profile?path=data/sprite/mouth/manifest.json&shinsekai_bridge_token=secret",
    ),
  );
});

it.each(["portrait.png", "idle.mp4"])(
  "renders cached poses for %s using video time and closes immediately on silence",
  async (src) => {
    const context = { setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn() };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    class PatchImage {
      onload?: () => void;
      value = "";
      set src(value: string) {
        this.value = value;
        queueMicrotask(() => this.onload?.());
      }
    }
    vi.stubGlobal("Image", PatchImage);
    let pending: FrameRequestCallback | null = null;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      pending = callback;
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {
      pending = null;
    });
    const profile: SpriteMouthManifest = {
      version: 1,
      width: 80,
      height: 120,
      fps: 24,
      duration: 2,
      patchBox: [30, 40, 50, 50],
      mouths: { closed: `${src}-closed.png`, half: `${src}-half.png`, open: `${src}-open.png` },
      correction: { offsetX: 0, offsetY: 0, scale: 1, rotation: 0, gain: 1 },
      track: [
        { time: 0, matrix: [1, 0, 0, 1, 0, 0] },
        { time: 2, matrix: [1, 0, 0, 1, 10, 20] },
      ],
    };
    const view = render(
      <SpriteMouthMedia src={src} alt="Mika" mouthProfile={profile} voiceCharacterName="render-test" />,
    );
    const media = view.container.querySelector("img,video")!;
    if (media instanceof HTMLVideoElement) {
      media.currentTime = 1;
      fireEvent.loadedData(media);
    } else fireEvent.load(media);
    await act(async () => {});
    const frame = (time: number) => {
      const callback = pending;
      pending = null;
      act(() => callback?.(time));
    };
    frame(100);
    expect(context.drawImage.mock.lastCall?.[0].value).toBe(`${src}-closed.png`);
    const [x, y] = src.endsWith("mp4") ? [35, 50] : [30, 40];
    expect(context.setTransform).toHaveBeenLastCalledWith(1, 0, 0, 1, x, y);
    act(() => routeAvatarVoice("render-test", 0.8));
    frame(200);
    expect(context.drawImage.mock.lastCall?.[0].value).toBe(`${src}-open.png`);
    act(() => routeAvatarVoice("render-test", 0));
    frame(201);
    expect(context.drawImage.mock.lastCall?.[0].value).toBe(`${src}-closed.png`);
    view.unmount();
    expect(pending).toBeNull();
  },
);
