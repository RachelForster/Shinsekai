import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Dialog, MediaPreviewDialog, type MediaPreview } from "../../../shared/ui";

function PreviewHarness({ media }: { media: MediaPreview }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open preview</button>
      <MediaPreviewDialog media={open ? media : null} closeLabel="Close preview" onClose={() => setOpen(false)} />
    </>
  );
}

describe("MediaPreviewDialog", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it.each(["backdrop", "canvas", "Escape", "close"])(
    "dismisses via %s, keeps image clicks inside, and restores keyboard focus",
    async (dismiss) => {
      render(<PreviewHarness media={{ src: "/sprite.png", title: "Sprite preview" }} />);
      const trigger = screen.getByRole("button", { name: "Open preview" });
      trigger.focus();
      fireEvent.click(trigger);
      const dialog = screen.getByRole("dialog", { name: "Sprite preview" });
      const close = screen.getByRole("button", { name: "Close preview" });
      await waitFor(() => expect(close).toHaveFocus());
      fireEvent.click(screen.getByAltText("Sprite preview"));
      expect(dialog).toBeInTheDocument();
      fireEvent.keyDown(close, { key: "Tab" });
      expect(close).toHaveFocus();
      fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
      expect(close).toHaveFocus();
      if (dismiss === "backdrop") fireEvent.click(dialog.parentElement!);
      else if (dismiss === "canvas") fireEvent.click(dialog.querySelector(".media-preview__canvas")!);
      else if (dismiss === "Escape") fireEvent.keyDown(close, { key: "Escape" });
      else fireEvent.click(close);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    },
  );

  it.each([true, false])("honors video playback and rate and releases the player on close (%s)", async (autoPlay) => {
    render(<PreviewHarness media={{ src: "/transition.webm", title: "Transition", playbackRate: 0.5, autoPlay }} />);
    fireEvent.click(screen.getByRole("button", { name: "Open preview" }));
    const video = screen.getByRole("dialog", { name: "Transition" }).querySelector("video")!;
    expect(video.playbackRate).toBe(0.5);
    expect(video.autoplay).toBe(autoPlay);
    fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
    expect(video).not.toBeInTheDocument();
    expect(video.getAttribute("src")).toBeNull();
  });

  it("keeps backdrop dismissal opt-in for other dialogs", () => {
    const close = vi.fn();
    const view = render(
      <Dialog title="Confirm" open onClose={close}>
        Unsaved changes
      </Dialog>,
    );
    fireEvent.click(screen.getByRole("dialog").parentElement!);
    expect(close).not.toHaveBeenCalled();
    view.rerender(
      <Dialog title="Confirm" open onClose={close} closeOnBackdrop dismissible={false}>
        Pending
      </Dialog>,
    );
    fireEvent.click(screen.getByRole("dialog").parentElement!);
    expect(close).not.toHaveBeenCalled();
  });

  it("keeps keyboard dismissal working after the image moves focus to the document", async () => {
    render(<PreviewHarness media={{ src: "/sprite.png", title: "Sprite preview" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Open preview" }));
    const close = screen.getByRole("button", { name: "Close preview" });
    await waitFor(() => expect(close).toHaveFocus());
    fireEvent.keyDown(document.body, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
