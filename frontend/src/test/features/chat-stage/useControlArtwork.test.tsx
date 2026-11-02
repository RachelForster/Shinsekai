import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useControlArtwork } from "../../../features/chat-stage/theme/useControlArtwork";
import { resolveChatTheme } from "../../../shared/theme/chatTheme";

const makeTheme = (suffix = "") =>
  resolveChatTheme(
    {
      schema: 1,
      id: "artwork",
      name: { en: "Artwork" },
      tokens: { send: { backgroundImage: `send${suffix}.png` }, input: { microphoneImage: `mic${suffix}.png` } },
    },
    (rel) => `https://themes.example/${rel}`,
  );

describe("control artwork fallback", () => {
  let images: HTMLImageElement[];
  beforeEach(() => {
    images = [];
    vi.stubGlobal(
      "Image",
      vi.fn(() => {
        const image = document.createElement("img");
        images.push(image);
        return image;
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  function load(image: HTMLImageElement, width = 48) {
    Object.defineProperty(image, "naturalWidth", { configurable: true, value: width });
    act(() => image.dispatchEvent(new Event("load")));
  }

  it("keeps both SVGs while loading and retains the failed image's fallback", () => {
    const theme = makeTheme();
    const { result } = renderHook(() => useControlArtwork(theme));
    expect(result.current.style["--chat-send-icon-opacity"]).toBe("1");
    expect(result.current.style["--chat-input-microphone-icon-opacity"]).toBe("1");
    load(images[0]);
    act(() => images[1].dispatchEvent(new Event("error")));
    expect(result.current.style["--chat-send-icon-opacity"]).toBe("0");
    expect(result.current.style["--chat-input-microphone-icon-opacity"]).toBe("1");
  });

  it("only hides the microphone SVG after successful loading", () => {
    const theme = makeTheme();
    const { result } = renderHook(() => useControlArtwork(theme));
    load(images[1], 0);
    expect(result.current.style["--chat-input-microphone-icon-opacity"]).toBe("1");
    load(images[1]);
    expect(result.current.style["--chat-input-microphone-icon-opacity"]).toBe("0");
    expect(result.current.style["--chat-send-icon-opacity"]).toBe("1");
  });

  it("restores SVGs on theme changes and ignores stale image callbacks", () => {
    const { result, rerender, unmount } = renderHook(({ theme }) => useControlArtwork(theme), {
      initialProps: { theme: makeTheme() },
    });
    const staleLoad = images[1].onload!;
    load(images[0]);
    rerender({ theme: makeTheme("-missing") });
    expect(result.current.style["--chat-send-icon-opacity"]).toBe("1");
    Object.defineProperty(images[1], "naturalWidth", { value: 48 });
    act(() => staleLoad.call(images[1], new Event("load")));
    expect(result.current.style["--chat-input-microphone-icon-opacity"]).toBe("1");
    load(images[2]);
    expect(result.current.style["--chat-send-icon-opacity"]).toBe("0");
    unmount();
    expect(images.every((image) => image.onload === null)).toBe(true);
  });
});
