import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SpriteGenerationDialog } from "../../../features/character-editor/SpriteGenerationDialog";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n";
import type { GeneratedCharacterSprite } from "../../../shared/platform/types";

const plan = vi.fn();
const draw = vi.fn();
const animate = vi.fn();
const save = vi.fn();
const capture = vi.fn();
const cutout = vi.fn();
const openFolder = vi.fn();
const openExternal = vi.fn();
vi.mock("../../../entities/character/repository", () => ({
  planCharacterSprites: (...args: unknown[]) => plan(...args),
  renderCharacterSprite: (...args: unknown[]) => draw(...args),
  animateCharacterSprite: (...args: unknown[]) => animate(...args),
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
function mount(subject = character) {
  const imported = vi.fn();
  const close = vi.fn();
  render(
    <I18nProvider language="en">
      <SpriteGenerationDialog character={subject} name="Mika" onClose={close} onImported={imported} />
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
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    animate.mockImplementation(async (input) => ({
      ...input,
      prompt: input.customPrompt ?? "idle with fixed camera",
      path: "idle-alpha.webm",
      taskId: "animation-result",
      animation: true,
      alphaVerified: true,
      backgroundRemoved: true,
    }));
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
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("guides planning, generation and saving while keeping settings visible", async () => {
    mount();
    const steps = screen.getByRole("list", { name: "Sprite generation steps" });
    expect(steps.querySelector('[aria-current="step"]')).toHaveTextContent("Set up & plan");
    expect(screen.getByRole("button", { name: "Add to collection (0)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Models & workflows" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Remove background automatically").closest("label")).toHaveClass("switch");
    await makePlan();
    expect(steps.querySelector('[aria-current="step"]')).toHaveTextContent("Generate & review");
    expect(screen.getByRole("button", { name: "Models & workflows" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Open workflow folder" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose reference image" })).toBeVisible();
    expect(screen.getByLabelText("Sprite 1 Tags")).toBeVisible();
    const prompt = screen.getByLabelText("Sprite 1 Image prompt");
    expect(prompt.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getAllByText("View / edit prompt")[0]);
    expect(prompt.closest("details")).toHaveAttribute("open");
    await drawAll();
    expect(steps.querySelector('[aria-current="step"]')).toHaveTextContent("Save to character");
    expect(screen.getByText("2 ready · 0 pending")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Models & workflows" }));
    expect(screen.getByRole("button", { name: "Open workflow folder" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled();
  });

  it("turns a static result into a tagged transparent animation and saves only the active tab", async () => {
    mount();
    await makePlan();
    await drawAll();
    fireEvent.click(screen.getAllByRole("button", { name: "Make animated sprite" })[0]);
    expect(screen.getByRole("tab", { name: "Animated sprites" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Add to collection (0)" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Gentle body sway" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Natural blinking" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await screen.findByText("Transparent WebM · alpha verified in every frame");
    expect(animate).toHaveBeenCalledWith(
      expect.objectContaining({
        referenceImage: "happy pose.png",
        tagging: "开心",
        breathing: true,
        blinking: true,
        breeze: false,
        loop: true,
      }),
      expect.anything(),
    );
    expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Add to collection (1)" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ name: "Mika", items: [{ taskId: "animation-result", tagging: "开心" }] }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Static sprites" }));
    expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled();
  });

  it("requires a source and blocks saving failed transparency until retry succeeds", async () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    expect(screen.getByRole("button", { name: "Generate transparent animation" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "Upload one image" }));
    fireEvent.click(screen.getByRole("button", { name: "Choose reference image" }));
    animate.mockResolvedValueOnce({
      name: "Mika",
      prompt: "idle",
      tagging: "平静",
      path: "original.mp4",
      videoPath: "original.mp4",
      taskId: "raw-animation",
      animation: true,
      alphaVerified: false,
      backgroundRemoved: false,
      backgroundRemovalError: "matting failed",
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("matting failed");
    expect(screen.getByRole("checkbox", { name: "Animation 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add to collection (0)" })).toBeDisabled();
    cutout.mockResolvedValueOnce({
      name: "Mika",
      prompt: "idle",
      tagging: "平静",
      path: "alpha.webm",
      taskId: "alpha",
      animation: true,
      alphaVerified: true,
      backgroundRemoved: true,
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry transparency processing" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    expect(animate).toHaveBeenCalledOnce();
    expect(draw).not.toHaveBeenCalled();
  });

  it("runs selected source images sequentially and inherits each image's own tags", async () => {
    mount({
      ...character,
      sprites: [{ path: "happy.png" }, { path: "skip.mp4" }, { path: "shy.png" }, { path: "skip.webm" }],
      emotion_tags: "立绘 1：开心，挥手\n立绘 2：视频标签\n立绘 3：害羞，交握\n立绘 4：透明视频标签\n",
    });
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    expect(screen.queryByRole("checkbox", { name: "Select Sprite 2" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Select Sprite 4" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Gentle breeze" }));
    expect(screen.getByRole("combobox", { name: "Motion speed" })).toHaveTextContent("Gentle · 0.75×");
    fireEvent.click(screen.getByRole("combobox", { name: "Motion speed" }));
    fireEvent.click(screen.getByRole("option", { name: "Slower · 0.5×" }));
    let finish!: (value: GeneratedCharacterSprite) => void;
    animate.mockImplementationOnce(
      () =>
        new Promise<GeneratedCharacterSprite>((resolve) => {
          finish = resolve;
        }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animations (2)" }));
    expect(animate).toHaveBeenCalledOnce();
    expect(screen.getByText("Queue: 1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose sources" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("group", { name: "Choose source sprites" })).not.toBeInTheDocument();
    expect(animate.mock.calls[0][0]).toEqual(
      expect.objectContaining({ referenceImage: "happy.png", tagging: "开心，挥手", breeze: true, playbackSpeed: 0.5 }),
    );
    await act(async () =>
      finish({
        name: "Mika",
        path: "happy-alpha.webm",
        prompt: "idle",
        tagging: "开心，挥手",
        taskId: "happy-video",
        animation: true,
        alphaVerified: true,
        backgroundRemoved: true,
      }),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled());
    expect(animate).toHaveBeenCalledTimes(2);
    expect(animate.mock.calls[1][0]).toEqual(
      expect.objectContaining({ referenceImage: "shy.png", tagging: "害羞，交握", breeze: true, playbackSpeed: 0.5 }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Choose sources" }));
    expect(screen.getByRole("checkbox", { name: "Select Sprite 1" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Add to collection (2)" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({
        name: "Mika",
        items: [
          { taskId: "happy-video", tagging: "开心，挥手" },
          { taskId: "animation-result", tagging: "害羞，交握" },
        ],
      }),
    );
  });

  it("continues past a failed animation and retries pending entries without duplicating plans", async () => {
    mount({
      ...character,
      sprites: [{ path: "one.png" }, { path: "two.png" }],
      emotion_tags: "立绘 1：微笑\n立绘 2：害羞\n",
    });
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    animate.mockRejectedValueOnce(new Error("first source failed"));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animations (2)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("first source failed");
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    expect(animate).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Continue pending animations (1)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled());
    expect(animate).toHaveBeenCalledTimes(3);
    expect(animate.mock.calls[2][0]).toEqual(expect.objectContaining({ referenceImage: "one.png", tagging: "微笑" }));
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("stops an animation batch after the current image and resumes the remaining plan", async () => {
    mount({ ...character, sprites: [{ path: "one.png" }, { path: "two.png" }] });
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    let finish!: (value: GeneratedCharacterSprite) => void;
    animate.mockImplementationOnce(
      () =>
        new Promise<GeneratedCharacterSprite>((resolve) => {
          finish = resolve;
        }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animations (2)" }));
    expect(screen.getByRole("button", { name: "Generate transparent animations (2)" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Stop after current image" }));
    await act(async () =>
      finish({
        name: "Mika",
        path: "first.webm",
        prompt: "idle",
        tagging: "平静，站立",
        taskId: "first",
        animation: true,
        alphaVerified: true,
        backgroundRemoved: true,
      }),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue pending animations (1)" })).toBeEnabled());
    expect(animate).toHaveBeenCalledOnce();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Continue pending animations (1)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled());
    expect(animate.mock.calls[1][0].referenceImage).toBe("two.png");
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("uses fallback tags only for untagged sources", async () => {
    mount({
      ...character,
      sprites: [{ path: "tagged.png" }, { path: "untagged.png" }],
      emotion_tags: "立绘 1：开心，挥手\n立绘 2：\n",
    });
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Default tags for untagged sprites" }), {
      target: { value: "放松，站立" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animations (2)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled());
    expect(animate.mock.calls[0][0].tagging).toBe("开心，挥手");
    expect(animate.mock.calls[1][0].tagging).toBe("放松，站立");
  });

  it("caps source selection to the available plan capacity and can clear it", () => {
    mount({ ...character, sprites: Array.from({ length: 14 }, (_, index) => ({ path: `sprite-${index}.png` })) });
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("button", { name: "Select first 12" }));
    expect(screen.getByText("12 source sprites selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Sprite 13" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generate transparent animations (12)" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByText("0 source sprites selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Sprite 13" })).toBeEnabled();
    expect(animate).not.toHaveBeenCalled();
  });

  it("writes a single static prompt without personality or LLM planning", async () => {
    mount({ ...character, character_setting: "" });
    expect(screen.getByRole("button", { name: "Plan prompts and tags" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Write one" }));
    const prompt = screen.getByRole("textbox", { name: "Sprite 1 Image prompt" });
    expect(prompt).toHaveFocus();
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled();
    expect(plan).not.toHaveBeenCalled();
    expect(draw).not.toHaveBeenCalled();
    fireEvent.change(prompt, { target: { value: "make the character stand and wave, fixed camera" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Sprite 1 Tags" }), { target: { value: "微笑，挥手" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    expect(draw).toHaveBeenCalledOnce();
    expect(draw).toHaveBeenCalledWith(
      expect.objectContaining({
        prompt: "make the character stand and wave, fixed camera",
        tagging: "微笑，挥手",
      }),
      expect.anything(),
    );
    expect(plan).not.toHaveBeenCalled();
  });

  it("writes one animated prompt using exactly one source and keeps its settings", async () => {
    mount({
      ...character,
      sprites: [{ path: "one.png" }, { path: "two.png" }],
      emotion_tags: "立绘 1：微笑，挥手\n立绘 2：平静，站立",
    });
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    expect(screen.getByRole("button", { name: "Write one" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    expect(screen.getByRole("button", { name: "Write one" })).toBeEnabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 2" }));
    expect(screen.getByRole("button", { name: "Write one" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Write one" }));
    expect(screen.queryByRole("button", { name: "Continue pending animations (1)" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled();
    const text = "让左手缓慢挥动，头发轻轻摆动，镜头固定。";
    fireEvent.change(screen.getByRole("textbox", { name: "Animation 1 Motion prompt" }), { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    expect(animate).toHaveBeenCalledWith(
      expect.objectContaining({
        customPrompt: text,
        referenceImage: "one.png",
        tagging: "微笑，挥手",
        loop: true,
        playbackSpeed: 0.75,
      }),
      expect.anything(),
    );
    expect(plan).not.toHaveBeenCalled();
    expect(draw).not.toHaveBeenCalled();
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  it("edits a generated animation, retains its preview on failure and redraws the latest prompt", async () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    fireEvent.click(screen.getByText("View / edit motion prompt"));
    const prompt = screen.getByRole("textbox", { name: "Animation 1 Motion prompt" });
    expect(prompt).not.toHaveAttribute("readonly");
    fireEvent.change(prompt, { target: { value: "custom hand motion, stationary camera" } });
    expect(screen.getByRole("button", { name: "Add to collection (0)" })).toBeDisabled();
    expect(screen.getByText("Prompt changed. Redraw before adding.")).toBeInTheDocument();
    animate.mockRejectedValueOnce(new Error("H3 temporarily unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Redraw" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("H3 temporarily unavailable");
    expect(screen.getByRole("article", { name: "Animation 1" }).querySelector("a")).toHaveAttribute(
      "href",
      "asset://idle-alpha.webm",
    );
    expect(screen.getByRole("button", { name: "Add to collection (0)" })).toBeDisabled();
    expect(animate).toHaveBeenLastCalledWith(
      expect.objectContaining({ customPrompt: "custom hand motion, stationary camera" }),
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Redraw" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    expect(prompt).toHaveValue("custom hand motion, stationary camera");
    fireEvent.change(prompt, { target: { value: "latest custom pose, locked camera" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue pending animations (1)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    expect(animate).toHaveBeenLastCalledWith(
      expect.objectContaining({ customPrompt: "latest custom pose, locked camera" }),
      expect.anything(),
    );
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(animate).toHaveBeenCalledTimes(4);
  });

  it("replaces one static result after choosing its target instead of appending", async () => {
    const { imported } = mount();
    await makePlan();
    await drawAll();
    fireEvent.click(screen.getAllByRole("button", { name: "Replace original sprite" })[0]);
    const dialog = screen.getByRole("dialog", { name: "Replace original sprite" });
    expect(within(dialog).getByRole("button", { name: "Confirm replacement" })).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("combobox", { name: "Sprite to replace" }));
    fireEvent.click(screen.getByRole("option", { name: "Sprite 1" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm replacement" }));
    await waitFor(() => expect(imported).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledWith({
      name: "Mika",
      items: [{ taskId: "task-happy pose", tagging: "开心" }],
      replace: { index: 0, path: "old.png" },
    });
    expect(screen.queryByRole("dialog", { name: "Replace original sprite" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  it("preselects an animation's source for replacement and retains the result after a failed save", async () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Replace original sprite" }));
    const dialog = screen.getByRole("dialog", { name: "Replace original sprite" });
    expect(within(dialog).getByRole("combobox", { name: "Sprite to replace" })).toHaveTextContent("Sprite 1");
    save.mockRejectedValueOnce(new Error("Original sprite changed"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm replacement" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Original sprite changed");
    expect(screen.getAllByRole("article")).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm replacement" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Replace original sprite" })).not.toBeInTheDocument(),
    );
    expect(save).toHaveBeenLastCalledWith({
      name: "Mika",
      items: [{ taskId: "animation-result", tagging: "平静，站立" }],
      replace: { index: 0, path: "old.png" },
    });
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

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
    fireEvent.click(screen.getByRole("button", { name: "Add more prompt plans" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("LLM unavailable");
    expect(screen.getByDisplayValue("happy pose")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[1]);
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close and discard unsaved ideas" }));
    expect(close).toHaveBeenCalledOnce();
  });
});
