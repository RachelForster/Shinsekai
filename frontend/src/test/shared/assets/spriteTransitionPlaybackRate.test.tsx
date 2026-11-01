import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  SPRITE_TRANSITION_RATE_STORAGE_KEY,
  setSpriteTransitionPlaybackRate,
  useSpriteTransitionPlaybackRate,
} from "../../../shared/assets/useSpriteTransitionPlaybackRate";

function Viewer({ name }: { name: string }) {
  return <output aria-label={name}>{useSpriteTransitionPlaybackRate()}</output>;
}

beforeEach(() => setSpriteTransitionPlaybackRate(1));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setSpriteTransitionPlaybackRate(1);
  window.localStorage.removeItem(SPRITE_TRANSITION_RATE_STORAGE_KEY);
});

it("updates all mounted consumers and saves the selected speed", () => {
  render(
    <>
      <Viewer name="preview" />
      <Viewer name="chat" />
    </>,
  );
  act(() => setSpriteTransitionPlaybackRate(0.75));
  expect(screen.getByLabelText("preview")).toHaveTextContent("0.75");
  expect(screen.getByLabelText("chat")).toHaveTextContent("0.75");
  expect(localStorage.getItem(SPRITE_TRANSITION_RATE_STORAGE_KEY)).toBe("0.75");
});

it("refreshes saved speed when remounted after another window changes it", () => {
  const view = render(<Viewer name="preview" />);
  view.unmount();
  localStorage.setItem(SPRITE_TRANSITION_RATE_STORAGE_KEY, "1.5");
  render(<Viewer name="chat" />);
  expect(screen.getByLabelText("chat")).toHaveTextContent("1.5");
});

it("synchronizes another window's changes and storage clearing", () => {
  render(<Viewer name="chat" />);
  act(() =>
    window.dispatchEvent(new StorageEvent("storage", { key: SPRITE_TRANSITION_RATE_STORAGE_KEY, newValue: "0.5" })),
  );
  expect(screen.getByLabelText("chat")).toHaveTextContent("0.5");
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: null, newValue: null })));
  expect(screen.getByLabelText("chat")).toHaveTextContent("1");
});

it.each(["broken", "0", "null", "4"])("uses normal speed for an invalid saved value: %s", (raw) => {
  localStorage.setItem(SPRITE_TRANSITION_RATE_STORAGE_KEY, raw);
  render(<Viewer name="preview" />);
  expect(screen.getByLabelText("preview")).toHaveTextContent("1");
});

it("keeps playback adjustable for this session when storage writes are blocked", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const view = render(<Viewer name="preview" />);
  act(() => setSpriteTransitionPlaybackRate(0.5));
  expect(screen.getByLabelText("preview")).toHaveTextContent("0.5");
  view.unmount();
  render(<Viewer name="chat" />);
  expect(screen.getByLabelText("chat")).toHaveTextContent("0.5");
});
