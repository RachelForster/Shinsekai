import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  useSpriteMouths,
  defaultMouthCorrection,
  type MouthCalibrationDraft,
} from "../../../features/character-editor/useSpriteMouths";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import type { GeneratedSpriteMouth } from "../../../shared/platform/types";

const generate = vi.fn();
const save = vi.fn();
vi.mock("../../../entities/character/repository", () => ({
  spriteMouthRepository: {
    generate: (...args: unknown[]) => generate(...args),
    save: (...args: unknown[]) => save(...args),
  },
}));
const character = { ...createCharacter(), name: "Mika", sprites: [{ path: "a.png" }, { path: "b.png" }] };
const draft: MouthCalibrationDraft = {
  manualEnabled: true,
  manual: { mouthBox: [0.4, 0.3, 0.6, 0.4], chin: [0.5, 0.5] },
  selectedFrames: { closed: 0, half: 1, open: 2 },
};
const ready = (path: string): GeneratedSpriteMouth => ({
  ready: true,
  taskId: `task-${path}`,
  reference: "reference.png",
  speechVideo: "speech.mp4",
  speechFps: 24,
  frames: [0, 1, 2].map((index) => ({ index, time: index / 24, path: `${index}.jpg` })),
  selectedFrames: draft.selectedFrames,
});
beforeEach(() => {
  generate.mockReset();
  generate.mockImplementation(async (input) => ready(input.spritePath));
  save.mockReset();
  save.mockResolvedValue(character);
});
afterEach(cleanup);

it("keeps frame choices, video, manual placement and corrections when reanalysis fails", async () => {
  const { result } = renderHook(() => useSpriteMouths(character, "Mika", vi.fn()));
  await act(async () => {
    await result.current.generate(["a.png"]);
  });
  act(() => {
    result.current.editDraft("a.png", draft);
    result.current.adjust("a.png", { ...defaultMouthCorrection, offsetX: 4 });
  });
  generate.mockResolvedValueOnce({ ready: false, taskId: "failed-retry", message: "unreliable landmarks" });
  await act(async () => {
    await result.current.reanalyse("a.png", {
      retryTaskId: "task-a.png",
      manual: draft.manual,
      selectedFrames: draft.selectedFrames,
      correction: { ...defaultMouthCorrection, offsetX: 4 },
    });
  });
  const item = result.current.items[0];
  expect(item.result?.frames).toHaveLength(3);
  expect(item.result?.speechVideo).toBe("speech.mp4");
  expect(item.result?.selectedFrames).toEqual(draft.selectedFrames);
  expect(item.result?.manual).toEqual(draft.manual);
  expect(item.draft).toEqual(draft);
  expect(item.applyFailed).toBe(true);
  expect(item.correction.offsetX).toBe(4);
  expect(result.current.selected).toHaveLength(0);
});

it("applies queued frame choices after the current generation even if another sprite is added", async () => {
  let finish!: (value: GeneratedSpriteMouth) => void;
  const pending = new Promise<GeneratedSpriteMouth>((resolve) => {
    finish = resolve;
  });
  generate.mockImplementation((input) =>
    input.spritePath === "b.png" ? pending : Promise.resolve(ready(input.spritePath)),
  );
  const { result, rerender } = renderHook(({ character }) => useSpriteMouths(character, "Mika", vi.fn()), {
    initialProps: { character },
  });
  let operation!: Promise<void>;
  act(() => {
    operation = result.current.generate(["a.png", "b.png"]);
  });
  await waitFor(() => expect(result.current.activePath).toBe("b.png"));
  act(() => {
    result.current.editDraft("a.png", { ...draft, manualEnabled: false });
    result.current.adjust("a.png", { ...defaultMouthCorrection, gain: 2 });
  });
  await act(async () => {
    await result.current.reanalyse("a.png", {
      retryTaskId: "task-a.png",
      selectedFrames: draft.selectedFrames,
      correction: { ...defaultMouthCorrection, gain: 2 },
    });
  });
  expect(result.current.pendingPaths).toEqual(["a.png"]);
  expect(generate).toHaveBeenCalledTimes(2);
  rerender({ character: { ...character, sprites: [...character.sprites, { path: "c.png" }] } });
  expect(result.current.pendingPaths).toEqual(["a.png"]);
  await act(async () => {
    finish(ready("b.png"));
    await operation;
  });
  expect(generate.mock.calls.map(([input]) => input.spritePath)).toEqual(["a.png", "b.png", "a.png"]);
  expect(result.current.items.find((item) => item.path === "a.png")?.correction.gain).toBe(2);
  expect(result.current.items.find((item) => item.path === "a.png")?.calibrationDirty).toBe(false);
  expect(result.current.selected.map((item) => item.path)).toEqual(["a.png", "b.png"]);
});

it("defers queued corrections while another generation tab is busy", async () => {
  const { result, rerender } = renderHook(({ external }) => useSpriteMouths(character, "Mika", vi.fn(), external), {
    initialProps: { external: false },
  });
  await act(async () => {
    await result.current.generate(["a.png"]);
  });
  rerender({ external: true });
  await act(async () => {
    await result.current.reanalyse("a.png", { retryTaskId: "task-a.png", selectedFrames: draft.selectedFrames });
  });
  expect(generate).toHaveBeenCalledTimes(1);
  expect(result.current.pendingPaths).toEqual(["a.png"]);
  rerender({ external: false });
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(result.current.busy).toBeNull());
});

it("applies a draft on close and can retry a failed save without reanalyzing", async () => {
  const { result } = renderHook(() => useSpriteMouths(character, "Mika", vi.fn()));
  await act(async () => {
    await result.current.generate(["a.png"]);
  });
  const correction = { ...defaultMouthCorrection, offsetX: 4 };
  act(() => {
    result.current.editDraft("a.png", draft);
    result.current.adjust("a.png", correction);
  });
  generate.mockResolvedValueOnce({ ...ready("a.png"), taskId: "reapplied", manual: draft.manual });
  save.mockRejectedValueOnce(new Error("save failed"));
  act(() => {
    result.current.finish(
      "a.png",
      { retryTaskId: "task-a.png", manual: draft.manual, selectedFrames: draft.selectedFrames, correction },
      "invalid frames",
    );
  });
  await waitFor(() => expect(result.current.items[0].error).toBe("save failed"));
  expect(result.current.items[0].saved).toBe(false);
  expect(result.current.items[0].result?.manual).toEqual(draft.manual);
  act(() => result.current.finish("a.png", undefined, "invalid frames"));
  await waitFor(() => expect(result.current.items[0].saved).toBe(true));
  expect(generate).toHaveBeenCalledTimes(2);
  expect(save).toHaveBeenCalledTimes(2);
  expect(save).toHaveBeenLastCalledWith({ name: "Mika", items: [{ taskId: "reapplied", correction }] });
});
