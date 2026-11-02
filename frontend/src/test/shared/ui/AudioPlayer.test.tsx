import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AudioPlayer } from "../../../shared/ui/AudioPlayer";

function setMediaNumber(element: HTMLMediaElement, property: "currentTime" | "duration", value: number) {
  Object.defineProperty(element, property, {
    configurable: true,
    value,
    writable: true,
  });
}

describe("AudioPlayer", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps only one player active globally", async () => {
    render(
      <>
        <AudioPlayer label="Track A" src="/audio/a.mp3" />
        <AudioPlayer label="Track B" src="/audio/b.mp3" />
      </>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Track A play" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Track A pause" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Track B play" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Track A play" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Track B pause" })).toBeInTheDocument();
    });
  });

  it("shows an error state when playback is rejected", async () => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.reject(new Error("blocked")));

    render(<AudioPlayer label="Broken audio" src="/audio/broken.mp3" />);
    fireEvent.click(screen.getByRole("button", { name: "Broken audio play" }));

    await waitFor(() => expect(document.querySelector('[data-state="error"]')).toBeInTheDocument());
    expect(screen.getByText("--:--")).toBeInTheDocument();
  });

  it("toggles mute and keeps the volume slider in sync", () => {
    render(<AudioPlayer label="Voice" src="/audio/voice.wav" />);

    const volume = screen.getByRole("slider", { name: "Voice volume" });
    expect(volume).toHaveValue("90");

    fireEvent.click(screen.getByRole("button", { name: "Voice mute" }));
    expect(screen.getByRole("button", { name: "Voice unmute" })).toBeInTheDocument();
    expect(volume).toHaveValue("0");

    fireEvent.change(volume, { target: { value: "35" } });
    expect(screen.getByRole("button", { name: "Voice mute" })).toBeInTheDocument();
    expect(volume).toHaveValue("35");
  });

  it("updates progress from native media events and seek changes", async () => {
    render(<AudioPlayer label="Theme" src="/audio/theme.mp3" />);

    fireEvent.click(screen.getByRole("button", { name: "Theme play" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Theme pause" })).toBeInTheDocument());

    const audio = document.querySelector("audio") as HTMLAudioElement;
    setMediaNumber(audio, "duration", 125);
    setMediaNumber(audio, "currentTime", 35);
    fireEvent(audio, new Event("loadedmetadata"));
    fireEvent(audio, new Event("timeupdate"));

    await waitFor(() => expect(screen.getByText("0:35")).toBeInTheDocument());
    expect(screen.getByText("2:05")).toBeInTheDocument();
    const progress = screen.getByRole("slider", { name: "Theme progress" });
    expect(Number(progress.getAttribute("value"))).toBeCloseTo(28);

    fireEvent.change(progress, { target: { value: "50" } });
    expect(audio.currentTime).toBe(62.5);
    expect(screen.getByText("1:02")).toBeInTheDocument();

    fireEvent(audio, new Event("ended"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Theme play" })).toBeInTheDocument());
    expect(screen.getAllByText("2:05")).toHaveLength(2);
  });

  it("warms up sources on hover and releases them when the source is cleared", () => {
    const { rerender, unmount } = render(<AudioPlayer label="Preview" preload="none" src="/audio/a.mp3" />);
    const audio = document.querySelector("audio") as HTMLAudioElement;
    const player = screen.getByRole("button", { name: "Preview play" }).closest(".audio-player") as HTMLElement;

    expect(audio.getAttribute("src")).toBeNull();
    fireEvent.pointerEnter(player);
    expect(audio.getAttribute("src")).toBe("/audio/a.mp3");

    rerender(<AudioPlayer label="Preview" preload="metadata" src="/audio/b.mp3" />);
    expect(audio.getAttribute("src")).toBe("/audio/b.mp3");

    rerender(<AudioPlayer label="Preview" preload="metadata" src="" />);
    expect(audio.getAttribute("src")).toBeNull();

    unmount();
    expect(audio.getAttribute("src")).toBeNull();
  });

  it("disables playback controls when no source is available", () => {
    render(<AudioPlayer label="Empty" src="" />);

    const playButton = screen.getByRole("button", { name: "Empty play" });
    expect(playButton).toBeDisabled();
    expect(screen.getByRole("button", { name: "Empty mute" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "Empty progress" })).toBeDisabled();

    fireEvent.click(playButton);
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });
});
