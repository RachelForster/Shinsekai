import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpriteMouthEditor } from "../../../features/character-editor/SpriteMouthEditor";
import { defaultMouthCorrection, type MouthCalibrationDraft } from "../../../features/character-editor/useSpriteMouths";
import { I18nProvider } from "../../../shared/i18n";

vi.mock("../../../entities/files/repository", () => ({ fileUrl: (path: string) => path }));
beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function mountEditable() {
  const draft = vi.fn();
  const apply = vi.fn();
  function Editable() {
    const [value, setValue] = useState<MouthCalibrationDraft>();
    return (
      <SpriteMouthEditor
        busy={false}
        onClose={vi.fn()}
        onAdjust={vi.fn()}
        onSaveEyes={vi.fn()}
        onDraftChange={(next) => {
          setValue(next);
          draft(next);
        }}
        onApply={apply}
        item={{
          path: "sprite.png",
          selected: false,
          correction: defaultMouthCorrection,
          draft: value,
          result: {
            ready: false,
            taskId: "manual",
            reference: "sprite.png",
            speechVideo: "speech.mp4",
            speechFps: 24,
            manual: { mouthBox: [0.4, 0.3, 0.6, 0.4], chin: [0.5, 0.45] },
            selectedFrames: { closed: 0, half: 1, open: 2 },
            frames: [0, 0.04, 0.1, 0.2].map((time, index) => ({ index, time, path: `${index}.jpg` })),
          },
        }}
      />
    );
  }
  const view = render(
    <I18nProvider language="en">
      <Editable />
    </I18nProvider>,
  );
  fireEvent.click(screen.getByLabelText("Show alignment guides"));
  return { ...view, draft, apply };
}

it("shows actual frame numbers and picks the paused frame for a mouth pose", () => {
  const { container, draft } = mountEditable();
  const video = container.ownerDocument.querySelector("video")!;
  video.currentTime = 0.12;
  fireEvent.timeUpdate(video);
  expect(screen.getByText("Frame 3 / 4")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next frame" }));
  expect(screen.getByText("Frame 4 / 4")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Use current frame as Half-open" }));
  expect(draft.mock.lastCall?.[0].selectedFrames.half).toBe(3);
  fireEvent.click(screen.getByRole("button", { name: "Preview Closed frame" }));
  expect(screen.getByText("Frame 1 / 4")).toBeInTheDocument();
  expect(video.currentTime).toBeLessThan(0.04);
});

it("scales anchor dragging with zoom, pans the canvas, and leaves source coordinates unchanged by reset", () => {
  vi.stubGlobal("PointerEvent", MouseEvent);
  const { draft } = mountEditable();
  const viewport = document.querySelector<HTMLElement>(".sprite-mouth-editor__viewport")!;
  const plane = document.querySelector<HTMLElement>(".sprite-mouth-editor__plane")!;
  Object.defineProperty(HTMLDivElement.prototype, "setPointerCapture", { value: vi.fn(), configurable: true });
  const mouth = screen.getByRole("button", { name: "Mouth region" });
  Object.defineProperty(mouth, "setPointerCapture", { value: vi.fn() });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const scale = this.classList.contains("sprite-mouth-editor__plane") ? Number(viewport.dataset.zoom) : 1;
    return {
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 400 * scale,
      bottom: 480 * scale,
      width: 400 * scale,
      height: 480 * scale,
      toJSON: () => ({}),
    };
  });
  fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
  expect(viewport.dataset.zoom).toBe("1.5");
  fireEvent.pointerDown(mouth, { button: 0, clientX: 100, clientY: 100 });
  fireEvent.pointerMove(mouth, { clientX: 160, clientY: 100 });
  fireEvent.pointerUp(mouth);
  expect(draft.mock.lastCall?.[0].manual.mouthBox).toEqual([0.5, 0.3, 0.7, 0.4]);
  const before = plane.style.transform;
  fireEvent.pointerDown(viewport, { button: 0, clientX: 200, clientY: 200 });
  fireEvent.pointerMove(viewport, { clientX: 220, clientY: 230 });
  fireEvent.pointerUp(viewport);
  expect(plane.style.transform).not.toBe(before);
  const calls = draft.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
  expect(viewport.dataset.zoom).toBe("1");
  expect(draft).toHaveBeenCalledTimes(calls);
  delete (HTMLDivElement.prototype as Partial<HTMLDivElement>).setPointerCapture;
});

it("zooms around the pointer with the wheel without scrolling the dialog", () => {
  const { draft } = mountEditable();
  const viewport = document.querySelector<HTMLElement>(".sprite-mouth-editor__viewport")!;
  const plane = document.querySelector<HTMLElement>(".sprite-mouth-editor__plane")!;
  vi.spyOn(viewport, "getBoundingClientRect").mockReturnValue(DOMRect.fromRect({ width: 400, height: 480 }));
  const wheel = (deltaY: number) =>
    fireEvent(
      viewport,
      new WheelEvent("wheel", { deltaY, clientX: 300, clientY: 140, bubbles: true, cancelable: true }),
    );
  expect(wheel(-250 * Math.log(2))).toBe(false);
  expect(viewport.dataset.zoom).toBe("2");
  expect(plane.style.transform).toBe("translate(-100px, 100px) scale(2)");
  expect(wheel(500)).toBe(false);
  expect(plane.style.transform).toBe("translate(0px, 0px) scale(1)");
  expect(draft).not.toHaveBeenCalled();
});

it("retains manual anchors and requires three distinct choices before submitting", () => {
  const { apply } = mountEditable();
  fireEvent.keyDown(screen.getByRole("button", { name: "Mouth region" }), { key: "ArrowRight" });
  fireEvent.keyDown(screen.getByRole("button", { name: "Chin anchor" }), { key: "ArrowDown" });
  fireEvent.click(screen.getByRole("combobox", { name: "Open" }));
  fireEvent.click(screen.getByRole("option", { name: "Frame 1" }));
  const submit = screen.getByRole("button", { name: "Apply frames and placement" });
  expect(submit).toBeDisabled();
  expect(screen.getByText("Choose a different frame for each of the three mouth poses.")).toBeVisible();
  fireEvent.click(submit);
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("combobox", { name: "Open" }));
  fireEvent.click(screen.getByRole("option", { name: "Frame 4" }));
  fireEvent.click(submit);
  expect(apply).toHaveBeenCalledWith(
    { mouthBox: [0.4 + 1 / 512, 0.3, 0.6 + 1 / 512, 0.4], chin: [0.5, 0.45 + 1 / 672] },
    { closed: 0, half: 1, open: 3 },
  );
});
