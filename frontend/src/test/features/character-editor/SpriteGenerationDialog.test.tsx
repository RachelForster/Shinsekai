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
const transition = vi.fn();
const analyzeTransitions = vi.fn();
const saveTransitions = vi.fn();
const openFolder = vi.fn();
const openExternal = vi.fn();
vi.mock("../../../entities/character/repository", () => ({
  planCharacterSprites: (...args: unknown[]) => plan(...args),
  renderCharacterSprite: (...args: unknown[]) => draw(...args),
  animateCharacterSprite: (...args: unknown[]) => animate(...args),
  importGeneratedCharacterSprites: (...args: unknown[]) => save(...args),
  captureCharacterSpriteFrame: (...args: unknown[]) => capture(...args),
  removeCharacterSpriteBackground: (...args: unknown[]) => cutout(...args),
  generateSpriteTransition: (...args: unknown[]) => transition(...args),
  analyzeSpriteTransitions: (...args: unknown[]) => analyzeTransitions(...args),
  saveSpriteTransitions: (...args: unknown[]) => saveTransitions(...args),
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
    analyzeTransitions.mockResolvedValue({
      name: "Mika",
      basis: "inferred",
      spritePaths: ["old.png", "animated.mp4", "sad.png"],
      dialogCount: 30,
      dialogLimit: 200,
      mappedDialogCount: 28,
      inferredDialogCount: 8,
      conversationCount: 2,
      transitionCount: 20,
      items: [
        {
          fromPath: "old.png",
          toPath: "animated.mp4",
          count: 8,
          probability: 0.4,
          conditionalProbability: 0.57,
          existing: true,
        },
        {
          fromPath: "old.png",
          toPath: "sad.png",
          count: 6,
          probability: 0.3,
          conditionalProbability: 0.43,
          existing: false,
        },
        {
          fromPath: "sad.png",
          toPath: "animated.mp4",
          count: 4,
          probability: 0.2,
          conditionalProbability: 1,
          existing: false,
        },
        {
          fromPath: "animated.mp4",
          toPath: "old.png",
          count: 2,
          probability: 0.1,
          conditionalProbability: 1,
          existing: false,
        },
      ],
    });
    transition.mockImplementation(async (input) => ({
      ...input,
      taskId: `transition-${input.fromPath}`,
      path: "transition-alpha.webm",
      alphaVerified: true,
      frameCount: 22,
      requestedFrames: 22,
    }));
    saveTransitions.mockResolvedValue({
      ...character,
      sprite_transitions: [
        {
          from_path: "old.png",
          to_path: "animated.mp4",
          path: "saved-alpha.webm",
          from_fingerprint: "a",
          to_fingerprint: "b",
          frame_count: 22,
        },
        {
          from_path: "animated.mp4",
          to_path: "old.png",
          path: "saved-reverse.webm",
          from_fingerprint: "b",
          to_fingerprint: "a",
          frame_count: 22,
        },
      ],
    });
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

  it("analyzes recent chats and generates exactly N selected one-way pairs instead of all source combinations", async () => {
    mount({ ...character, sprites: [...character.sprites, { path: "sad.png" }] });
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Recommended count N (one-way)" }), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze recent chats" }));
    const recommendations = await screen.findByRole("region", { name: "Chat recommendations" });
    expect(analyzeTransitions).toHaveBeenCalledWith(
      { name: "Mika" },
      expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
    );
    expect(within(recommendations).getByText("2 selected · 50.0% of sample changes covered")).toBeInTheDocument();
    expect(within(recommendations).getByText(/8 records inferred by the LLM/)).toBeInTheDocument();
    const checkboxes = within(recommendations).getAllByRole("checkbox");
    expect(checkboxes[0]).toBeDisabled();
    expect(checkboxes[0]).not.toBeChecked();
    expect(checkboxes[1]).toBeChecked();
    expect(checkboxes[2]).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    await waitFor(() => expect(transition).toHaveBeenCalledTimes(2));
    expect(transition.mock.calls.map(([input]) => [input.fromPath, input.toPath])).toEqual([
      ["old.png", "sad.png"],
      ["sad.png", "animated.mp4"],
    ]);
    expect(analyzeTransitions).toHaveBeenCalledOnce();
    await screen.findByRole("button", { name: "Save 2 transitions" });
  });

  it("changes N locally, allows pair overrides, and can include existing clips or return to manual pairing", async () => {
    mount({ ...character, sprites: [...character.sprites, { path: "sad.png" }] });
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    fireEvent.click(screen.getByRole("button", { name: "Analyze recent chats" }));
    const recommendations = await screen.findByRole("region", { name: "Chat recommendations" });
    const count = screen.getByRole("spinbutton", { name: "Recommended count N (one-way)" });
    fireEvent.change(count, { target: { value: "1" } });
    expect(within(recommendations).getByText("1 selected · 30.0% of sample changes covered")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Skip available transitions" }));
    expect(within(recommendations).getByText("1 selected · 40.0% of sample changes covered")).toBeInTheDocument();
    const pairs = within(recommendations).getAllByRole("checkbox");
    fireEvent.click(pairs[0]);
    fireEvent.click(pairs[3]);
    expect(within(recommendations).getByText("1 selected · 10.0% of sample changes covered")).toBeInTheDocument();
    expect(analyzeTransitions).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Manual selection" }));
    expect(screen.queryByRole("region", { name: "Chat recommendations" })).toBeNull();
    expect(screen.getByText("Choose sprites (at least two)")).toBeInTheDocument();
  });

  it("keeps analysis errors actionable without starting H3 or hiding manual selection", async () => {
    analyzeTransitions.mockRejectedValue(new Error("No recent chats for this character"));
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    fireEvent.click(screen.getByRole("button", { name: "Analyze recent chats" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No recent chats for this character");
    expect(screen.getByRole("button", { name: "Analyze recent chats" })).toBeEnabled();
    expect(transition).not.toHaveBeenCalled();
    expect(screen.getByText("Choose sprites (at least two)")).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("tab", { name: "Choose a file" }));
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

  it("shows automatic screen matting and reprocesses the original animation without rendering H3 again", async () => {
    const result = {
      name: "Mika",
      prompt: "idle",
      tagging: "平静",
      taskId: "animation-result",
      path: "idle-alpha.webm",
      videoPath: "idle-original.mp4",
      animation: true,
      alphaVerified: true,
      backgroundRemoved: true,
      matting: { method: "chroma", alphaMatting: true, screenColor: [0, 255, 0] },
    };
    animate.mockResolvedValueOnce(result);
    cutout.mockResolvedValueOnce({ ...result, taskId: "refined", path: "refined-alpha.webm" });
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await screen.findByText("Automatic screen keying · Refined alpha edges");
    fireEvent.click(screen.getByRole("button", { name: "Redo matting" }));
    await waitFor(() =>
      expect(cutout).toHaveBeenCalledWith({ name: "Mika", taskId: "animation-result" }, expect.anything()),
    );
    expect(animate).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
  });

  it("can redo matting of a completed transition without requesting a new H3 render", async () => {
    transition.mockImplementation(async (input) => ({
      ...input,
      taskId: input.retryTaskId ? "refined-transition" : `clip-${input.fromPath}`,
      path: "clip-alpha.webm",
      videoPath: "original.mp4",
      alphaVerified: true,
      frameCount: 22,
      requestedFrames: 22,
      matting: { method: "chroma", alphaMatting: true, screenColor: [255, 0, 255] },
    }));
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 2 transitions" })).toBeEnabled());
    fireEvent.click(screen.getAllByRole("button", { name: "Redo matting" })[0]);
    await waitFor(() => expect(transition).toHaveBeenCalledTimes(3));
    expect(transition.mock.calls[2][0]).toEqual(
      expect.objectContaining({ retryTaskId: "clip-old.png", regenerate: false }),
    );
  });

  it("runs selected source images sequentially and inherits each image's own tags", async () => {
    mount({
      ...character,
      sprites: [{ path: "happy.png" }, { path: "skip.mp4" }, { path: "shy.png" }, { path: "skip.webm" }],
      emotion_tags: "立绘 1：开心，挥手\n立绘 2：视频标签\n立绘 3：害羞，交握\n立绘 4：透明视频标签\n",
    });
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    expect(screen.getByRole("checkbox", { name: "Select Sprite 2" })).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: "Select Sprite 4" })).toBeEnabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 3" }));
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

  it("batches saved MP4 and transparent WebM sprites as paused first-frame sources with their tags", async () => {
    mount({
      ...character,
      sprites: [{ path: "/clips/opaque.mp4" }, { path: "/clips/transparent.webm" }],
      emotion_tags: "立绘 1：微笑，挥手\n立绘 2：害羞，交握",
    });
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    const sources = screen.getByRole("group", { name: "Choose source sprites" });
    const videos = sources.querySelectorAll("video");
    expect(videos).toHaveLength(2);
    for (const video of videos) expect(video).not.toHaveAttribute("autoplay");
    expect(screen.getByText(/Animated sprites use their first frame/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animations (2)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled());
    expect(animate.mock.calls.map(([input]) => [input.referenceImage, input.tagging])).toEqual([
      ["/clips/opaque.mp4", "微笑，挥手"],
      ["/clips/transparent.webm", "害羞，交握"],
    ]);
    expect(save).not.toHaveBeenCalled();
  });

  it("regenerates a new animation from its transparent result instead of its original reference", async () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Regenerate from first frame" }));
    expect(screen.getByRole("checkbox", { name: "Select New sprite 1" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled());
    expect(animate.mock.calls[0][0].referenceImage).toBe("animated.mp4");
    expect(animate.mock.calls[1][0]).toEqual(
      expect.objectContaining({ referenceImage: "idle-alpha.webm", loop: true, playbackSpeed: 0.75 }),
    );
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(save).not.toHaveBeenCalled();
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

  it("replaces all selected animation sources in one request and retains results when saving fails", async () => {
    const { imported } = mount({
      ...character,
      emotion_tags: "立绘 1：微笑，挥手\n立绘 2：害羞，交握",
    });
    animate.mockImplementation(async (input) => ({
      ...input,
      taskId: `task-${input.referenceImage}`,
      prompt: "idle",
      path: `${input.referenceImage}-alpha.webm`,
      animation: true,
      alphaVerified: true,
    }));
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animations (2)" }));
    const button = await screen.findByRole("button", { name: "Replace selected originals (2)" });
    await waitFor(() => expect(button).toBeEnabled());
    save.mockRejectedValueOnce(new Error("Save failed"));
    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(imported).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() => expect(imported).toHaveBeenCalledWith(expect.anything(), [0, 1]));
    expect(save).toHaveBeenLastCalledWith({
      name: "Mika",
      items: [
        { taskId: "task-old.png", tagging: "微笑，挥手", replace: { index: 0, path: "old.png" } },
        { taskId: "task-animated.mp4", tagging: "害羞，交握", replace: { index: 1, path: "animated.mp4" } },
      ],
    });
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace selected originals (0)" })).toBeDisabled();
  });

  it("preserves the original through first-frame regeneration and requires one result per original", async () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Replace selected originals (1)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Regenerate from first frame" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Replace selected originals (2)" })).toBeDisabled();
    expect(screen.getByText("Select only one result per original to replace.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Animation 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace selected originals (1)" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledWith({
      name: "Mika",
      items: [{ taskId: "animation-result", tagging: "平静，站立", replace: { index: 0, path: "old.png" } }],
    });
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  it("explains when selected new sprites have no originals instead of guessing their targets", async () => {
    mount();
    await makePlan();
    await drawAll();
    expect(screen.getByRole("button", { name: "Replace selected originals (2)" })).toBeDisabled();
    expect(screen.getByText(/Some results have no original/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to collection (2)" })).toBeEnabled();
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

  it("generates both directed pairs from mixed media and saves transitions separately from sprites", async () => {
    const { imported } = mount();
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    expect(screen.getByText("0 selected · 0 clips")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate / resume 0 clips" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 2" }));
    expect(screen.getByText("2 selected · 2 clips")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 2 transitions" })).toBeEnabled());
    expect(transition.mock.calls.map(([input]) => [input.fromPath, input.toPath])).toEqual([
      ["old.png", "animated.mp4"],
      ["animated.mp4", "old.png"],
    ]);
    expect(plan).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save 2 transitions" }));
    await waitFor(() =>
      expect(imported).toHaveBeenCalledWith(expect.objectContaining({ sprite_transitions: expect.any(Array) })),
    );
    expect(saveTransitions).toHaveBeenCalledWith({
      name: "Mika",
      items: [{ taskId: "transition-old.png" }, { taskId: "transition-animated.mp4" }],
    });
    expect(save).not.toHaveBeenCalled();
    expect(screen.getAllByText("22 frames · saved · plays on sprite change")).toHaveLength(2);
  });

  it("keeps legacy five-frame previews and upgrades them when generating the new batch", async () => {
    mount({
      ...character,
      sprite_transitions: [
        {
          from_path: "old.png",
          to_path: "animated.mp4",
          path: "legacy.webm",
          from_fingerprint: "a",
          to_fingerprint: "b",
        },
      ],
    });
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    expect(screen.getByText("5 frames · saved · plays on sprite change")).toBeInTheDocument();
    expect(screen.getByText("22 frames · normal speed · ~0.92 s · transparent")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 2 transitions" })).toBeEnabled());
    expect(transition).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("22-frame transparent clip · unsaved")).toHaveLength(2);
  });

  it("keeps MP4 and transparent WebM source previews paused on their first frame", () => {
    mount({ ...character, sprites: [{ path: "/clips/idle.mp4" }, { path: "/clips/idle-alpha.webm" }] });
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    const picker = screen.getByRole("group", { name: "Choose sprites (at least two)" });
    const videos = [...picker.querySelectorAll("video")];
    expect(videos).toHaveLength(2);
    for (const video of videos) {
      expect(video.autoplay).toBe(false);
      expect(video.loop).toBe(false);
      expect(video.controls).toBe(false);
      Object.defineProperty(video, "duration", { value: 4 });
      fireEvent.loadedMetadata(video);
      expect(video.currentTime).toBe(0.001);
    }
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("keeps pending directed pairs when stopped and resumes without repeating a completed clip", async () => {
    let finish!: (result: unknown) => void;
    transition.mockImplementationOnce(
      (input) =>
        new Promise((resolve) => {
          finish = (result) => resolve({ ...input, ...(result as object) });
        }),
    );
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop after this clip" }));
    await act(async () => finish({ taskId: "one", path: "first-alpha.webm", alphaVerified: true, frameCount: 22 }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 1 transitions" })).toBeEnabled());
    expect(transition).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 1 clips" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 2 transitions" })).toBeEnabled());
    expect(transition).toHaveBeenCalledTimes(2);
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
