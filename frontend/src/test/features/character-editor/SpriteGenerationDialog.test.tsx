import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SpriteGenerationDialog } from "../../../features/character-editor/SpriteGenerationDialog";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n";
import type { GeneratedCharacterSprite } from "../../../shared/platform/types";

const plan = vi.fn();
const draw = vi.fn();
const save = vi.fn();
const capture = vi.fn();
const cutout = vi.fn();
const openFolder = vi.fn();
const openExternal = vi.fn();
vi.mock("../../../entities/character/repository", () => ({
  planCharacterSprites: (...args: unknown[]) => plan(...args),
  renderCharacterSprite: (...args: unknown[]) => draw(...args),
  importGeneratedCharacterSprites: (...args: unknown[]) => save(...args),
  captureCharacterSpriteFrame: (...args: unknown[]) => capture(...args),
  removeCharacterSpriteBackground: (...args: unknown[]) => cutout(...args),
}));
vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
  openT2iWorkflowFolder: () => openFolder(),
  openExternal: (url: string) => openExternal(url),
}));
vi.mock("../../../shared/ui", async (original) => ({
  ...(await original<typeof import("../../../shared/ui")>()),
  FilePicker: ({
    onPathChange,
    pickLabel,
    disabled,
  }: {
    onPathChange: (path: string) => void;
    pickLabel: string;
    disabled: boolean;
  }) => (
    <button aria-label={pickLabel} disabled={disabled} onClick={() => onPathChange("reference.png")}>
      {pickLabel}
    </button>
  ),
}));

const character = {
  ...createCharacter(),
  name: "Mika",
  character_setting: "Unsaved shy personality",
  sprites: [{ path: "old.png" }, { path: "animated.mp4" }],
};
const pairs = [
  { prompt: "happy pose", tagging: "开心" },
  { prompt: "shy pose", tagging: "害羞" },
];
function mount() {
  const imported = vi.fn();
  const close = vi.fn();
  render(
    <I18nProvider language="en">
      <SpriteGenerationDialog character={character} name="Mika" onClose={close} onImported={imported} />
    </I18nProvider>,
  );
  return { imported, close };
}
async function makePlan() {
  fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Plan prompts and tags" }));
  await screen.findByDisplayValue("happy pose");
}
async function drawAll() {
  fireEvent.click(screen.getByRole("button", { name: "Generate pending (2)" }));
  await waitFor(() => expect(draw).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled());
}

describe("sprite generator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    openFolder.mockResolvedValue({ path: "C:/Shinsekai/ai/t2i/workflows" });
    openExternal.mockResolvedValue(undefined);
    plan.mockResolvedValue({ items: pairs });
    draw.mockImplementation(async (input) => ({
      ...input,
      path: `${input.prompt}.png`,
      taskId: `task-${input.prompt}`,
    }));
    save.mockResolvedValue({ ...character, sprites: [...character.sprites, { path: "new.png" }] });
  });
  afterEach(cleanup);

  it("opens the active workflow folder and official model and setup pages", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Open workflow folder" }));
    await screen.findByText("Workflow folder: C:/Shinsekai/ai/t2i/workflows");
    expect(openFolder).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "H3 model downloads" }));
    fireEvent.click(screen.getByRole("button", { name: "H3 setup guide" }));
    expect(openExternal).toHaveBeenCalledWith("https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main");
    expect(openExternal).toHaveBeenCalledWith("https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native");
    fireEvent.click(screen.getByText("First use: connect an image generation service"));
    fireEvent.click(screen.getByRole("link", { name: "minimax_h3_fl2va_pruned_int8_convrot.safetensors" }));
    expect(openExternal).toHaveBeenCalledWith(
      "https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    );
    expect(screen.getByText("models/diffusion_models/")).toBeInTheDocument();
    expect(screen.getByText("models/text_encoders/")).toBeInTheDocument();
    expect(screen.getByText("models/vae/")).toBeInTheDocument();
    expect(screen.getByText("models/loras/")).toBeInTheDocument();
    expect(draw).not.toHaveBeenCalled();
  });

  it("reports folder failures and keeps download links available for retry", async () => {
    openFolder.mockRejectedValueOnce(new Error("file manager unavailable"));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Open workflow folder" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("file manager unavailable");
    expect(screen.getByRole("button", { name: "H3 model downloads" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Open workflow folder" }));
    await screen.findByText("Workflow folder: C:/Shinsekai/ai/t2i/workflows");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("plans from the latest personality with a reference, then imports only selected tagged images", async () => {
    const { imported } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Choose reference image" }));
    await makePlan();
    expect(plan).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Mika",
        setting: "Unsaved shy personality",
        count: 2,
        referenceImage: "reference.png",
      }),
      expect.anything(),
    );
    expect(draw).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Sprite 1 Image prompt"), { target: { value: "edited happy pose" } });
    await drawAll();
    expect(draw).toHaveBeenCalledWith(
      expect.objectContaining({ prompt: "edited happy pose", tagging: "开心", referenceImage: "reference.png" }),
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Sprite 2" }));
    fireEvent.change(screen.getByLabelText("Sprite 1 Tags"), { target: { value: "微笑，日常" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to collection (1)" }));
    await waitFor(() => expect(imported).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledWith({
      name: "Mika",
      items: [{ taskId: "task-edited happy pose", tagging: "微笑，日常" }],
    });
    expect(screen.queryByDisplayValue("edited happy pose")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("shy pose")).toBeInTheDocument();
  });

  it("preserves successful previews after redraw failure and requires a redraw after prompt edits", async () => {
    mount();
    await makePlan();
    await drawAll();
    draw.mockRejectedValueOnce(new Error("ComfyUI disconnected"));
    fireEvent.click(screen.getAllByRole("button", { name: "Redraw" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("ComfyUI disconnected");
    expect(screen.getByAltText("Sprite 1")).toHaveAttribute("src", "asset://happy pose.png");
    fireEvent.change(screen.getByLabelText("Sprite 1 Image prompt"), { target: { value: "different pose" } });
    expect(screen.getByRole("checkbox", { name: "Sprite 1" })).toBeDisabled();
    expect(screen.getByText("Prompt changed. Redraw before adding.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled();
    fireEvent.click(screen.getAllByRole("button", { name: "Redraw" })[0]);
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Sprite 1" })).toBeEnabled());
    expect(screen.getByAltText("Sprite 1")).toHaveAttribute("src", "asset://different pose.png");
  });

  it("continues the queue after one failure and keeps selection on save failure", async () => {
    mount();
    await makePlan();
    draw.mockRejectedValueOnce(new Error("first failed"));
    fireEvent.click(screen.getByRole("button", { name: "Generate pending (2)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    expect(draw).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("alert")).toHaveTextContent("first failed");
    save.mockRejectedValueOnce(new Error("disk full"));
    fireEvent.click(screen.getByRole("button", { name: "Add to collection (1)" }));
    expect(await screen.findByText("disk full")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Sprite 2" })).toBeChecked();
  });

  it("recaptures a video without rerendering, preserves the old preview on failure, and saves the new tagged frame", async () => {
    mount();
    draw.mockImplementation(async (input) => ({
      ...input,
      path: `${input.prompt}.png`,
      videoPath: `${input.prompt}.mp4`,
      frameTime: 2,
      taskId: `task-${input.prompt}`,
    }));
    await makePlan();
    await drawAll();
    const video = screen.getByLabelText("Sprite 1 Source video") as HTMLVideoElement;
    Object.defineProperty(video, "duration", { value: 4 });
    vi.spyOn(video, "pause").mockImplementation(() => {});
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(2);
    video.currentTime = 1.25;
    fireEvent.timeUpdate(video);
    fireEvent.change(screen.getByLabelText("Sprite 1 Tags"), { target: { value: "edited tags" } });
    capture.mockRejectedValueOnce(new Error("frame failed"));
    fireEvent.click(screen.getByRole("button", { name: "Use frame at 1.25s" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("frame failed");
    expect(screen.getByAltText("Sprite 1")).toHaveAttribute("src", "asset://happy pose.png");
    capture.mockResolvedValueOnce({
      ...pairs[0],
      name: "Mika",
      path: "selected.png",
      videoPath: "happy pose.mp4",
      frameTime: 1.25,
      taskId: "new-frame",
    });
    fireEvent.click(screen.getByRole("button", { name: "Use frame at 1.25s" }));
    await waitFor(() => expect(screen.getByAltText("Sprite 1")).toHaveAttribute("src", "asset://selected.png"));
    expect(capture).toHaveBeenLastCalledWith(
      { name: "Mika", taskId: "task-happy pose", seconds: 1.25, removeBackground: true },
      expect.anything(),
    );
    expect(draw).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("checkbox", { name: "Sprite 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to collection (1)" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ name: "Mika", items: [{ taskId: "new-frame", tagging: "edited tags" }] }),
    );
  });

  it("stops a batch after the current render and prevents duplicate requests", async () => {
    mount();
    await makePlan();
    let resolve!: (value: GeneratedCharacterSprite) => void;
    draw.mockImplementationOnce(
      () =>
        new Promise<GeneratedCharacterSprite>((done) => {
          resolve = done;
        }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Generate pending (2)" }));
    expect(screen.getByRole("button", { name: "Generate pending (2)" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Stop after current image" }));
    await act(async () => resolve({ ...pairs[0], name: "Mika", path: "one.png", taskId: "one" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    expect(draw).toHaveBeenCalledOnce();
  });

  it("defaults to automatic cutout, can opt out, and retries a failed cutout without redrawing", async () => {
    mount();
    expect(screen.getByRole("checkbox", { name: "Remove background automatically" })).toBeChecked();
    await makePlan();
    draw.mockImplementation(async (input) => ({
      ...input,
      taskId: "raw",
      path: "raw.png",
      backgroundRemoved: false,
      backgroundRemovalError: "model unavailable",
    }));
    await drawAll();
    expect(draw).toHaveBeenCalledWith(expect.objectContaining({ removeBackground: true }), expect.anything());
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent("Original image kept");
    cutout.mockRejectedValueOnce(new Error("retry failed"));
    fireEvent.click(screen.getAllByRole("button", { name: "Retry background removal" })[0]);
    expect(await screen.findByText("retry failed")).toBeInTheDocument();
    expect(screen.getByAltText("Sprite 1")).toHaveAttribute("src", "asset://raw.png");
    cutout.mockResolvedValueOnce({
      ...pairs[0],
      name: "Mika",
      taskId: "cutout",
      path: "cutout.png",
      backgroundRemoved: true,
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Retry background removal" })[0]);
    await waitFor(() => expect(screen.getByAltText("Sprite 1")).toHaveAttribute("src", "asset://cutout.png"));
    expect(screen.getByText("Background removed · transparent PNG")).toBeInTheDocument();
    expect(draw).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("checkbox", { name: "Remove background automatically" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Redraw" })[0]);
    await waitFor(() => expect(draw).toHaveBeenCalledTimes(3));
    expect(draw).toHaveBeenLastCalledWith(expect.objectContaining({ removeBackground: false }), expect.anything());
  });

  it("retains ideas when planning fails and confirms discarding unsaved previews", async () => {
    const { close } = mount();
    await makePlan();
    plan.mockRejectedValueOnce(new Error("LLM unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Plan prompts and tags" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("LLM unavailable");
    expect(screen.getByDisplayValue("happy pose")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[1]);
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close and discard unsaved ideas" }));
    expect(close).toHaveBeenCalledOnce();
  });
});
