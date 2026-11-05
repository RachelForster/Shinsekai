import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SpriteGenerationPage } from "../../../features/character-editor/SpriteGenerationPage";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n";
import type { GeneratedCharacterSprite } from "../../../shared/platform/types";
import {
  setSpriteTransitionPlaybackRate,
  SPRITE_TRANSITION_RATE_STORAGE_KEY,
} from "../../../shared/assets/useSpriteTransitionPlaybackRate";

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
const mouths = { status: vi.fn(), generate: vi.fn(), save: vi.fn(), remove: vi.fn() };
vi.mock("../../../entities/character/repository", () => ({
  spriteMouthRepository: {
    status: (...args: unknown[]) => mouths.status(...args),
    generate: (...args: unknown[]) => mouths.generate(...args),
    save: (...args: unknown[]) => mouths.save(...args),
    remove: (...args: unknown[]) => mouths.remove(...args),
  },
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
      <SpriteGenerationPage character={subject} name="Mika" onClose={close} onImported={imported} />
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
    setSpriteTransitionPlaybackRate(1);
    vi.clearAllMocks();
    mouths.status.mockResolvedValue({
      runtimeReady: true,
      modelsReady: true,
      compatible: true,
      missing: [],
      version: [3, 13],
      pythonPath: "python.exe",
      device: "auto",
      models: [],
      modelDirectory: "models",
    });
    mouths.generate.mockImplementation(async (input) => ({
      ready: true,
      taskId: `mouth-${input.spritePath}`,
      spritePath: input.spritePath,
      frames: [0, 1, 2].map((index) => ({ index, path: `${index}.jpg` })),
      selectedFrames: { closed: 0, half: 1, open: 2 },
    }));
    mouths.save.mockResolvedValue({
      ...character,
      sprites: [{ path: "old.png", mouth_sync: "manifest.json" }, { path: "animated.mp4" }],
    });
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
    setSpriteTransitionPlaybackRate(1);
  });

  it("opens a workspace with a close action instead of a modal", () => {
    const { close } = mount();
    expect(screen.getByRole("region", { name: "Generate sprites" })).toHaveClass("sprite-generation");
    expect(screen.queryByRole("dialog", { name: "Generate sprites" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Generate sprites", level: 1 })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(close).toHaveBeenCalledOnce();
  });

  it("uses an animated sprite as a paused first-frame reference for static generation", async () => {
    mount({ ...character, sprites: [{ path: "/sprites/animated.webm" }] });
    fireEvent.click(screen.getByRole("combobox", { name: "Use an existing sprite" }));
    fireEvent.click(screen.getByRole("option", { name: "Sprite 1 · Animated · first frame" }));
    const preview = document.querySelector<HTMLVideoElement>(".sprite-generation__reference-image video")!;
    expect(preview).not.toBeNull();
    expect(preview.autoplay).toBe(false);
    expect(preview.loop).toBe(false);
    Object.defineProperty(preview, "duration", { value: 4 });
    fireEvent.loadedMetadata(preview);
    expect(preview.currentTime).toBeLessThan(0.01);
    expect(screen.getByText("Uses the video's first frame as reference, preserving framing and alpha.")).toBeVisible();
    await makePlan();
    await drawAll();
    expect(draw).toHaveBeenCalledWith(
      expect.objectContaining({ referenceImage: "/sprites/animated.webm" }),
      expect.anything(),
    );
  });

  it("dismisses a dropdown with Escape without leaving the page", () => {
    const { close } = mount();
    const select = screen.getByRole("combobox", { name: "Preview size" });
    fireEvent.click(select);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(select, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Generate sprites", level: 1 })).toBeVisible();
  });

  it("enlarges previews across tabs without starting another generation", () => {
    mount();
    fireEvent.click(screen.getByRole("combobox", { name: "Preview size" }));
    fireEvent.click(screen.getByRole("option", { name: "Large preview" }));
    expect(document.querySelector('[data-sprite-preview-size="large"]')).not.toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    expect(screen.getByRole("combobox", { name: "Preview size" })).toHaveTextContent("Large preview");
    expect(document.querySelector('[data-sprite-preview-size="large"]')).not.toBeNull();
    expect(draw).not.toHaveBeenCalled();
    expect(animate).not.toHaveBeenCalled();
    expect(transition).not.toHaveBeenCalled();
  });

  it("opens a result overlay and returns to the same scroll position and selection", async () => {
    const { close } = mount();
    await makePlan();
    await drawAll();
    const body = document.querySelector<HTMLElement>(".sprite-generation__workspace-body")!;
    body.scrollTop = 123;
    const trigger = screen.getByRole("button", { name: "View sprite 1 full size" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Sprite 1" });
    fireEvent.click(within(dialog).getByAltText("Sprite 1"));
    expect(dialog).toBeInTheDocument();
    fireEvent.click(dialog.parentElement!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Sprite 1" })).toBeChecked();
    expect(body.scrollTop).toBe(123);
    expect(trigger).toHaveFocus();
    expect(draw).toHaveBeenCalledTimes(2);
    expect(close).not.toHaveBeenCalled();
  });

  it("enlarges a video reference while preserving its paused first-frame mode", () => {
    mount({ ...character, sprites: [{ path: "/sprites/reference.webm" }] });
    fireEvent.click(screen.getByRole("combobox", { name: "Use an existing sprite" }));
    fireEvent.click(screen.getByRole("option", { name: "Sprite 1 · Animated · first frame" }));
    fireEvent.click(screen.getByRole("button", { name: "Enlarge preview: Reference image or video (optional)" }));
    const dialog = screen.getByRole("dialog", { name: "Reference image or video (optional)" });
    const video = within(dialog).getByLabelText("Reference image or video (optional)") as HTMLVideoElement;
    expect(video.autoplay).toBe(false);
    expect(video.loop).toBe(false);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(draw).not.toHaveBeenCalled();
  });

  it("defaults to ToonOut and shares the selected fallback model across sprite modes", async () => {
    mount();
    expect(screen.getByRole("combobox", { name: "Background removal model" })).toHaveTextContent("ToonOut");
    fireEvent.click(screen.getByRole("combobox", { name: "Background removal model" }));
    fireEvent.click(screen.getByRole("option", { name: "ISNet Anime" }));
    await makePlan();
    await drawAll();
    expect(draw).toHaveBeenCalledWith(expect.objectContaining({ mattingModel: "isnet-anime" }), expect.anything());
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    expect(screen.getByRole("combobox", { name: "Background removal model" })).toHaveTextContent("ISNet Anime");
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    expect(screen.getByRole("combobox", { name: "Background removal model" })).toHaveTextContent("ISNet Anime");
  });

  it("uses the selected H3 resolution for a batch and a redraw while keeping animation settings separate", async () => {
    mount();
    expect(screen.getByRole("combobox", { name: "H3 generation resolution" })).toHaveTextContent("Follow workflow");
    fireEvent.click(screen.getByRole("combobox", { name: "H3 generation resolution" }));
    fireEvent.click(screen.getByRole("option", { name: "High · ~0.7 MP" }));
    await makePlan();
    await drawAll();
    expect(draw.mock.calls.map(([input]) => input.h3Resolution)).toEqual(["hd", "hd"]);
    fireEvent.click(screen.getByRole("combobox", { name: "H3 generation resolution" }));
    fireEvent.click(screen.getByRole("option", { name: "Ultra · ~1 MP" }));
    expect(draw).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getAllByRole("button", { name: "Redraw" })[0]);
    await waitFor(() => expect(draw).toHaveBeenCalledTimes(3));
    expect(draw).toHaveBeenLastCalledWith(expect.objectContaining({ h3Resolution: "native" }), expect.anything());
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Redraw" })[0]).toBeEnabled());
    fireEvent.click(screen.getAllByRole("button", { name: "Make animated sprite" })[0]);
    expect(screen.getByRole("combobox", { name: "H3 generation resolution" })).toHaveTextContent("Follow workflow");
    fireEvent.click(screen.getByRole("combobox", { name: "H3 generation resolution" }));
    fireEvent.click(screen.getByRole("option", { name: "High · ~0.7 MP" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await waitFor(() => expect(animate).toHaveBeenCalledOnce());
    expect(animate.mock.calls[0][0]).toHaveProperty("h3Resolution", "hd");
  });

  it("locks the H3 resolution while generation is running", async () => {
    let finish!: (value: GeneratedCharacterSprite) => void;
    draw.mockImplementationOnce(() => new Promise<GeneratedCharacterSprite>((resolve) => (finish = resolve)));
    mount();
    await makePlan();
    fireEvent.click(screen.getByRole("button", { name: "Generate pending (2)" }));
    await waitFor(() => expect(draw).toHaveBeenCalledOnce());
    expect(screen.getByRole("combobox", { name: "H3 generation resolution" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    await act(async () => finish({ name: "Mika", ...pairs[0], path: "high.png", taskId: "high" }));
    await waitFor(() => expect(draw).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "H3 generation resolution" })).toBeEnabled());
  });

  it("shows the actual model and a fallback explanation on generated stills", async () => {
    draw.mockImplementation(async (input) => ({
      ...input,
      path: `${input.prompt}.png`,
      taskId: `task-${input.prompt}`,
      backgroundRemoved: true,
      matting: {
        method: "ai",
        model: "isnet-anime",
        requestedModel: "toonout",
        alphaMatting: false,
        device: "cpu",
        fallbackReason: "toonout-unavailable",
      },
    }));
    mount();
    await makePlan();
    await drawAll();
    expect(
      screen.getAllByText("AI background removal · ISNet Anime · CPU · ToonOut unavailable; using fallback"),
    ).toHaveLength(2);
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
    cutout.mockResolvedValueOnce({
      ...result,
      taskId: "refined",
      path: "refined-alpha.webm",
      matting: { method: "ai", alphaMatting: false },
    });
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Animated sprites" }));
    const screenOption = screen.getByRole("checkbox", { name: "Automatic color screen (experimental)" });
    const alphaOption = screen.getByRole("checkbox", { name: "Alpha edge refinement (experimental)" });
    expect(screenOption).not.toBeChecked();
    expect(alphaOption).not.toBeChecked();
    fireEvent.click(screenOption);
    fireEvent.click(alphaOption);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate transparent animation" }));
    await screen.findByText("Automatic screen keying · Alpha matting enabled");
    expect(animate).toHaveBeenCalledWith(
      expect.objectContaining({ autoScreen: true, alphaMatting: true }),
      expect.anything(),
    );
    fireEvent.click(screenOption);
    fireEvent.click(alphaOption);
    fireEvent.click(screen.getByRole("button", { name: "Redo matting" }));
    await waitFor(() =>
      expect(cutout).toHaveBeenCalledWith(
        { name: "Mika", taskId: "animation-result", autoScreen: false, alphaMatting: false, mattingModel: "toonout" },
        expect.anything(),
      ),
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
    fireEvent.click(screen.getByRole("checkbox", { name: "Automatic color screen (experimental)" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Alpha edge refinement (experimental)" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 2 transitions" })).toBeEnabled());
    expect(transition.mock.calls[0][0]).toEqual(expect.objectContaining({ autoScreen: true, alphaMatting: true }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Automatic color screen (experimental)" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Alpha edge refinement (experimental)" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Redo matting" })[0]);
    await waitFor(() => expect(transition).toHaveBeenCalledTimes(3));
    expect(transition.mock.calls[2][0]).toEqual(
      expect.objectContaining({
        retryTaskId: "clip-old.png",
        regenerate: false,
        autoScreen: false,
        alphaMatting: false,
      }),
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
    expect(screen.getByRole("article", { name: "Animation 1" }).querySelector("img, video")).toHaveAttribute(
      "src",
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
      { name: "Mika", taskId: "task-happy pose", seconds: 1.25, removeBackground: true, mattingModel: "toonout" },
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
    fireEvent.click(screen.getByRole("combobox", { name: "H3 generation resolution" }));
    fireEvent.click(screen.getByRole("option", { name: "High · ~0.7 MP" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 2 transitions" })).toBeEnabled());
    expect(transition.mock.calls.map(([input]) => [input.fromPath, input.toPath])).toEqual([
      ["old.png", "animated.mp4"],
      ["animated.mp4", "old.png"],
    ]);
    expect(transition.mock.calls.map(([input]) => input.h3Resolution)).toEqual(["hd", "hd"]);
    fireEvent.click(screen.getByRole("combobox", { name: "H3 generation resolution" }));
    fireEvent.click(screen.getByRole("option", { name: "Ultra · ~1 MP" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    await waitFor(() => expect(transition).toHaveBeenCalledTimes(4));
    expect(transition.mock.calls.slice(2).map(([input]) => input.h3Resolution)).toEqual(["native", "native"]);
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 2 transitions" })).toBeEnabled());
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
    expect(screen.getByText("22 frames · 1× · ~0.92 s · transparent")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate / resume 2 clips" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save 2 transitions" })).toBeEnabled());
    expect(transition).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("22-frame transparent clip · unsaved")).toHaveLength(2);
  });

  it("adjusts saved transition previews immediately and remembers the speed without generating again", () => {
    const subject = {
      ...character,
      sprite_transitions: [
        {
          from_path: "old.png",
          to_path: "animated.mp4",
          path: "/clips/saved-speed.webm",
          from_fingerprint: "a",
          to_fingerprint: "b",
          frame_count: 22,
        },
      ],
    };
    mount(subject);
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    const preview = document.querySelector<HTMLVideoElement>(".sprite-transitions__preview video")!;
    expect(preview.playbackRate).toBe(1);
    preview.currentTime = 0.2;
    fireEvent.click(screen.getByRole("combobox", { name: "Transition playback speed" }));
    fireEvent.click(screen.getByRole("option", { name: "0.5×" }));
    expect(screen.getByText("22 frames · 0.5× · ~1.83 s · transparent")).toBeInTheDocument();
    expect(preview.playbackRate).toBe(0.5);
    expect(preview.currentTime).toBe(0.2);
    expect(localStorage.getItem(SPRITE_TRANSITION_RATE_STORAGE_KEY)).toBe("0.5");
    expect(transition).not.toHaveBeenCalled();
    cleanup();
    mount(subject);
    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    expect(screen.getByRole("combobox", { name: "Transition playback speed" })).toHaveTextContent("0.5×");
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

  it("prepares mouths for selected images and videos and saves bindings without adding portraits", async () => {
    const { imported } = mount();
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    await waitFor(() => expect(mouths.status).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Prepare selected mouths (2)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Prepare selected mouths (2)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save mouth profiles (2)" })).toBeEnabled());
    expect(mouths.generate.mock.calls.map(([input]) => input.spritePath)).toEqual(["old.png", "animated.mp4"]);
    expect(mouths.generate.mock.calls.every(([input]) => input.frameCount === 22)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Save mouth profiles (2)" }));
    await waitFor(() => expect(imported).toHaveBeenCalledOnce());
    expect(mouths.save).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Mika",
        items: expect.arrayContaining([
          expect.objectContaining({ taskId: "mouth-old.png" }),
          expect.objectContaining({ taskId: "mouth-animated.mp4" }),
        ]),
      }),
    );
    expect(draw).not.toHaveBeenCalled();
  });

  it("queues more than 12 mouths and retries only the unsaved results after a save batch fails", async () => {
    const sprites = Array.from({ length: 25 }, (_, index) => ({ path: `portrait-${index + 1}.png` }));
    mouths.save
      .mockResolvedValueOnce({ ...character, sprites })
      .mockRejectedValueOnce(new Error("Mouth batch save failed"))
      .mockResolvedValue({ ...character, sprites });
    mount({ ...character, sprites });
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    const prepare = screen.getByRole("button", { name: "Prepare selected mouths (25)" });
    await waitFor(() => expect(prepare).toBeEnabled());
    fireEvent.click(prepare);
    const saveBatch = await screen.findByRole("button", { name: "Save mouth profiles (25)" });
    await waitFor(() => expect(saveBatch).toBeEnabled());
    expect(mouths.generate.mock.calls.map(([input]) => input.spritePath)).toEqual(sprites.map((sprite) => sprite.path));

    fireEvent.click(saveBatch);
    expect(await screen.findByRole("alert")).toHaveTextContent("Mouth batch save failed");
    expect(screen.getAllByText("Saved", { exact: true })).toHaveLength(12);
    expect(mouths.save).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Save mouth profiles (13)" }));
    await waitFor(() => expect(screen.getAllByText("Saved", { exact: true })).toHaveLength(25));
    const saveCalls = mouths.save.mock.calls.map(([input]) =>
      input.items.map(({ taskId }: { taskId: string }) => taskId),
    );
    expect(saveCalls.map((ids) => ids.length)).toEqual([12, 12, 12, 1]);
    expect(saveCalls[2]).toEqual(saveCalls[1]);
    expect([saveCalls[0], saveCalls[2], saveCalls[3]].flat()).toEqual(sprites.map((sprite) => `mouth-${sprite.path}`));
    expect(screen.getAllByRole("button", { name: "Preview and correct" })[0]).toBeEnabled();
  });

  it("uses the selected shorter length for generation and the current choice for regeneration", async () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    fireEvent.change(screen.getByLabelText("Talking clip length"), { target: { value: "5" } });
    expect(screen.getByText(/Five frames may not contain all three mouth poses/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Prepare selected mouths (1)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Prepare selected mouths (1)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Regenerate talking clip" })).toBeEnabled());
    expect(mouths.generate.mock.calls[0][0].frameCount).toBe(5);
    fireEvent.change(screen.getByLabelText("Talking clip length"), { target: { value: "39" } });
    fireEvent.click(screen.getByRole("button", { name: "Regenerate talking clip" }));
    await waitFor(() => expect(mouths.generate).toHaveBeenCalledTimes(2));
    expect(mouths.generate.mock.calls[1][0]).toEqual(expect.objectContaining({ frameCount: 39, regenerate: true }));
  });

  it("previews and adjusts a finished mouth while the next portrait is generating", async () => {
    const original = mouths.generate.getMockImplementation()!;
    let finishSecond!: (value: unknown) => void;
    const second = new Promise((resolve) => {
      finishSecond = resolve;
    });
    mouths.generate.mockImplementation((input, ...rest) =>
      input.spritePath === "animated.mp4" ? second : original(input, ...rest),
    );
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Prepare selected mouths (2)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Prepare selected mouths (2)" }));
    await waitFor(() => expect(mouths.generate).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("tab", { name: "Static sprites" }));
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Preview and correct" })[0]);
    fireEvent.change(screen.getByLabelText("Horizontal offset"), { target: { value: "3" } });
    fireEvent.click(screen.getByLabelText("Show alignment guides"));
    fireEvent.keyDown(screen.getByRole("button", { name: "Chin anchor" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("button", { name: "Apply frames and placement" }));
    expect(mouths.generate).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Queued to apply after the current generation" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save and close" }));
    await act(async () => {
      finishSecond({ ready: true, taskId: "second", frames: [], selectedFrames: { closed: 0, half: 1, open: 2 } });
    });
    await waitFor(() => expect(mouths.generate).toHaveBeenCalledTimes(3));
    expect(mouths.generate.mock.calls[2][0]).toEqual(
      expect.objectContaining({ retryTaskId: "mouth-old.png", correction: expect.objectContaining({ offsetX: 3 }) }),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Save mouth profiles (1)" })).toBeEnabled());
    expect(mouths.save).toHaveBeenCalledWith({
      name: "Mika",
      items: [{ taskId: "mouth-old.png", correction: expect.objectContaining({ offsetX: 3 }) }],
    });
  });

  it("keeps the three frame selectors and manual anchors after an unsuccessful apply", async () => {
    mouths.generate.mockResolvedValueOnce({
      ready: false,
      taskId: "original",
      frames: [0, 1, 2].map((index) => ({ index, path: `${index}.jpg` })),
      selectedFrames: { closed: 0, half: 1, open: 2 },
    });
    mouths.generate.mockResolvedValueOnce({ ready: false, taskId: "retry", message: "landmarks unreliable" });
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Prepare selected mouths (1)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Prepare selected mouths (1)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Preview and correct" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Preview and correct" }));
    fireEvent.click(screen.getByLabelText("Show alignment guides"));
    fireEvent.keyDown(screen.getByRole("button", { name: "Mouth region" }), { key: "ArrowRight" });
    fireEvent.click(screen.getByRole("button", { name: "Apply frames and placement" }));
    await waitFor(() => expect(mouths.generate).toHaveBeenCalledTimes(2));
    await screen.findAllByText("landmarks unreliable");
    const closed = screen.getByRole("combobox", { name: "Closed" });
    fireEvent.click(closed);
    expect(screen.getAllByRole("option")).toHaveLength(3);
    fireEvent.click(screen.getByRole("option", { name: "Frame 1" }));
    expect(screen.getByLabelText("Show alignment guides")).toBeChecked();
    mouths.generate.mockResolvedValueOnce({ ready: false, taskId: "retry-again", message: "landmarks unreliable" });
    fireEvent.click(screen.getByRole("button", { name: "Save and close" }));
    await waitFor(() => expect(mouths.generate).toHaveBeenCalledTimes(3));
    fireEvent.click(screen.getByRole("button", { name: "Preview and correct" }));
    expect(screen.getByLabelText("Show alignment guides")).toBeChecked();
    expect(mouths.save).not.toHaveBeenCalled();
  });

  it("enlarges the hover preview and saves hand placement and frames when the editor closes", async () => {
    mouths.generate.mockImplementation(async (input) => ({
      ready: true,
      taskId: input.retryTaskId ? "applied-manual" : `mouth-${input.spritePath}`,
      reference: "reference.png",
      frames: [0, 1, 2, 3].map((index) => ({ index, path: `${index}.jpg` })),
      selectedFrames: input.selectedFrames ?? { closed: 0, half: 1, open: 2 },
      manual: input.manual,
      profile: {
        width: 512,
        height: 672,
        patchBox: [20, 30, 40, 50],
        mouths: { closed: "closed.png", half: "half.png", open: "open.png" },
      },
    }));
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all sources" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Prepare selected mouths (2)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Prepare selected mouths (2)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save mouth profiles (2)" })).toBeEnabled());
    const card = document.querySelector(".sprite-mouth-card")!;
    fireEvent.mouseEnter(card);
    expect(document.querySelector(".sprite-mouth-hover-preview canvas")).toBeInTheDocument();
    fireEvent.mouseLeave(card);
    expect(document.querySelector(".sprite-mouth-hover-preview")).not.toBeInTheDocument();
    const edit = () => fireEvent.click(screen.getAllByRole("button", { name: "Preview and correct" })[0]);
    edit();
    fireEvent.click(screen.getByLabelText("Show alignment guides"));
    fireEvent.keyDown(screen.getByRole("button", { name: "Mouth region" }), { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("button", { name: "Chin anchor" }), { key: "ArrowDown" });
    const mouthStyle = screen.getByRole("button", { name: "Mouth region" }).getAttribute("style");
    const chinStyle = screen.getByRole("button", { name: "Chin anchor" }).getAttribute("style");
    fireEvent.change(screen.getByLabelText("Horizontal offset"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("combobox", { name: "Open" }));
    fireEvent.click(screen.getByRole("option", { name: "Frame 4" }));
    const submit = screen.getByRole("button", { name: "Apply frames and placement" });
    fireEvent.click(submit);
    await waitFor(() => expect(screen.getByLabelText("Simulate speech")).toBeEnabled());
    expect(mouths.generate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        retryTaskId: "mouth-old.png",
        manual: {
          mouthBox: [0.45 + 1 / 512, 0.35, 0.55 + 1 / 512, 0.38],
          chin: [0.5, 0.42 + 1 / 672],
        },
        selectedFrames: { closed: 0, half: 1, open: 3 },
        correction: expect.objectContaining({ offsetX: 3 }),
      }),
      expect.anything(),
    );
    expect(screen.getByRole("dialog").querySelector(".sprite-mouth-media__overlay")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Show alignment guides"));
    expect(screen.queryByRole("button", { name: "Mouth region" })).not.toBeInTheDocument();
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Close and save adjustments" }));
    await waitFor(() =>
      expect(mouths.save).toHaveBeenCalledWith({
        name: "Mika",
        items: [{ taskId: "applied-manual", correction: expect.objectContaining({ offsetX: 3 }) }],
      }),
    );
    edit();
    expect(screen.getByRole("button", { name: "Restore automatic placement" })).toBeVisible();
    fireEvent.click(screen.getByLabelText("Show alignment guides"));
    expect(screen.getByRole("button", { name: "Mouth region" })).toHaveAttribute("style", mouthStyle);
    expect(screen.getByRole("button", { name: "Chin anchor" })).toHaveAttribute("style", chinStyle);
    expect(screen.getByRole("combobox", { name: "Open" })).toHaveTextContent("Frame 4");
    expect(screen.getByLabelText("Horizontal offset")).toHaveValue(3);
    fireEvent.click(screen.getByRole("button", { name: "Save and close" }));
    expect(mouths.save).toHaveBeenCalledTimes(1);
  });

  it("recalculates tracking for a saved animated sprite using its current mouth frames", async () => {
    const manual = { mouthBox: [0.43, 0.36, 0.55, 0.39], chin: [0.5, 0.42] };
    const selectedFrames = { closed: 0, half: 2, open: 1 };
    mouths.generate.mockResolvedValueOnce({
      ready: true,
      cached: true,
      taskId: "previous-track",
      frames: [0, 1, 2].map((index) => ({ index, path: `${index}.jpg` })),
      selectedFrames,
      manual,
    });
    const savedSprite = { path: "animated.mp4", mouth_sync: "old-track.json" };
    mount({ ...character, sprites: [savedSprite] });
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Prepare selected mouths (1)" }));
    const preview = await screen.findByRole("button", { name: "Preview and correct" });
    await waitFor(() => expect(preview).toBeEnabled());
    fireEvent.click(preview);
    fireEvent.click(screen.getByRole("button", { name: "Apply frames and placement" }));
    await waitFor(() => expect(mouths.generate).toHaveBeenCalledTimes(2));
    expect(mouths.generate.mock.calls[1][0]).toEqual(
      expect.objectContaining({ retryTaskId: "previous-track", selectedFrames, manual }),
    );
    expect(mouths.generate.mock.calls[1][0].regenerate).toBeUndefined();
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply frames and placement" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Save and close" }));
    await waitFor(() => expect(mouths.save).toHaveBeenCalledOnce());
  });

  it("reuses a failed mouth clip when applying manually chosen frames", async () => {
    mouths.generate.mockResolvedValueOnce({
      ready: false,
      taskId: "needs-correction",
      frames: [0, 1, 2].map((index) => ({ index, path: `${index}.jpg` })),
      selectedFrames: { closed: 0, half: 1, open: 2 },
    });
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Sprite 1" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Prepare selected mouths (1)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Prepare selected mouths (1)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Preview and correct" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Preview and correct" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply frames and placement" }));
    await waitFor(() => expect(mouths.generate).toHaveBeenCalledTimes(2));
    expect(mouths.generate.mock.calls[1][0]).toEqual(
      expect.objectContaining({ retryTaskId: "needs-correction", selectedFrames: { closed: 0, half: 1, open: 2 } }),
    );
    expect(mouths.generate.mock.calls[1][0].regenerate).toBeUndefined();
  });

  it("retains ideas when planning fails and confirms discarding unsaved previews", async () => {
    const { close } = mount();
    await makePlan();
    plan.mockRejectedValueOnce(new Error("LLM unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Add more prompt plans" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("LLM unavailable");
    expect(screen.getByDisplayValue("happy pose")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close and discard unsaved ideas" }));
    expect(close).toHaveBeenCalledOnce();
  });
});
