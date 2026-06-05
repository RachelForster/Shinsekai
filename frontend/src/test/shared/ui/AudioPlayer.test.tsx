import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AudioPlayer } from "../../../shared/ui/AudioPlayer";

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
});
