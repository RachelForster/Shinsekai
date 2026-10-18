import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SpriteGenerationDialog } from "../../../features/character-editor/SpriteGenerationDialog";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n";
import type { GeneratedCharacterSprite } from "../../../shared/platform/types";

const plan = vi.fn();
const draw = vi.fn();
const save = vi.fn();
vi.mock("../../../entities/character/repository", () => ({
  planCharacterSprites: (...args: unknown[]) => plan(...args),
  renderCharacterSprite: (...args: unknown[]) => draw(...args),
  importGeneratedCharacterSprites: (...args: unknown[]) => save(...args),
}));
vi.mock("../../../entities/files/repository", () => ({ fileUrl: (path: string) => `asset://${path}` }));
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
    plan.mockResolvedValue({ items: pairs });
    draw.mockImplementation(async (input) => ({
      ...input,
      path: `${input.prompt}.png`,
      taskId: `task-${input.prompt}`,
    }));
    save.mockResolvedValue({ ...character, sprites: [...character.sprites, { path: "new.png" }] });
  });
  afterEach(cleanup);

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
