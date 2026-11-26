// @ts-ignore -- Vitest runs in Node; Node types may or may not be visible to the app tsconfig.
import { readFileSync } from "node:fs";

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SpriteGenerationPage } from "../../../features/character-editor/SpriteGenerationPage";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n";

const mouthsStatus = vi.fn();

vi.mock("../../../entities/character/repository", () => ({
  spriteMouthRepository: {
    status: (...args: unknown[]) => mouthsStatus(...args),
    generate: vi.fn(),
    save: vi.fn(),
    remove: vi.fn(),
  },
  planCharacterSprites: vi.fn(),
  renderCharacterSprite: vi.fn(),
  animateCharacterSprite: vi.fn(),
  importGeneratedCharacterSprites: vi.fn(),
  captureCharacterSpriteFrame: vi.fn(),
  removeCharacterSpriteBackground: vi.fn(),
  generateSpriteTransition: vi.fn(),
  analyzeSpriteTransitions: vi.fn(),
  saveSpriteTransitions: vi.fn(),
}));

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
  openT2iWorkflowFolder: vi.fn(),
  openExternal: vi.fn(),
}));

const spritePageCss: string = readFileSync("src/features/character-editor/SpriteGenerationPage.css", "utf8");

function renderSpritePage() {
  const character = {
    ...createCharacter(),
    name: "Mika",
    character_setting: "Shy classmate",
    sprites: [{ path: "old.png" }],
  };
  render(
    <I18nProvider language="en">
      <SpriteGenerationPage character={character} name="Mika" onClose={vi.fn()} onImported={vi.fn()} />
    </I18nProvider>,
  );
}

describe("SpriteGenerationPage compact header layout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mouthsStatus.mockResolvedValue({
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
  });

  afterEach(() => {
    cleanup();
  });

  it("renders title, character name, mode tabs, preview controls, and close action inside the top header", () => {
    renderSpritePage();

    const header = document.querySelector<HTMLElement>("header.sprite-generation__header");
    expect(header).not.toBeNull();
    const withinHeader = within(header!);

    expect(withinHeader.getByRole("heading", { name: "Generate sprites", level: 1 })).toBeVisible();
    expect(withinHeader.getByText("Mika")).toHaveClass("sprite-generation__character-name");

    const tablist = withinHeader.getByRole("tablist", { name: "Sprite generation mode" });
    expect(within(tablist).getAllByRole("tab")).toHaveLength(4);

    expect(withinHeader.getByRole("combobox", { name: "Preview size" })).toBeVisible();
    expect(withinHeader.getByRole("checkbox", { name: "Color backdrop" })).toBeVisible();
    expect(withinHeader.getByRole("button", { name: "Close" })).toBeVisible();
  });

  it("keeps steps and truncated intro with tooltip in the slim journey bar and updates across tabs", async () => {
    renderSpritePage();

    const journey = document.querySelector<HTMLElement>(".sprite-generation__journey");
    expect(journey).not.toBeNull();
    const withinJourney = within(journey!);

    expect(withinJourney.queryByRole("tablist")).not.toBeInTheDocument();
    const stepsList = withinJourney.getByRole("list", { name: "Sprite generation steps" });
    expect(stepsList).toHaveTextContent("Set up & plan");

    const staticIntro =
      "Plan sprites for Mika, review the prompts, generate images, then add your favorites to the existing collection.";
    const introNode = journey!.querySelector<HTMLElement>(".sprite-generation__intro");
    expect(introNode).toHaveTextContent(staticIntro);
    expect(introNode).toHaveAttribute("title", staticIntro);

    fireEvent.click(screen.getByRole("tab", { name: "Transitions" }));
    const transitionIntro =
      "Recommend common one-way transitions from recent chats or pair sprites manually. Each transparent clip has 22 frames and plays on sprite changes after saving.";
    expect(stepsList).toHaveTextContent("Choose pairs");
    expect(introNode).toHaveTextContent(transitionIntro);
    expect(introNode).toHaveAttribute("title", transitionIntro);

    fireEvent.click(screen.getByRole("tab", { name: "Mouth sync" }));
    await waitFor(() => expect(mouthsStatus).toHaveBeenCalledTimes(1));
    const mouthIntro =
      "Create three mouth poses for selected images or videos. Video portraits use their first frame and a cached tracking path; voice volume drives playback.";
    expect(stepsList).toHaveTextContent("Choose portraits");
    expect(introNode).toHaveTextContent(mouthIntro);
    expect(introNode).toHaveAttribute("title", mouthIntro);
  });

  it("enforces compact single-row CSS rules for the journey bar, intro text, and workspace header", () => {
    const journeyBlock = spritePageCss.split(".sprite-generation__journey {")[1]?.split("}")[0] ?? "";
    const introBlock = spritePageCss.split(".sprite-generation__intro {")[1]?.split("}")[0] ?? "";
    const workspaceTitleBlock =
      spritePageCss.split(".sprite-generation__workspace-header > div:first-child {")[1]?.split("}")[0] ?? "";

    expect(journeyBlock).toContain("display: flex;");
    expect(journeyBlock).toContain("align-items: center;");
    expect(introBlock).toContain("text-overflow: ellipsis;");
    expect(introBlock).toContain("white-space: nowrap;");
    expect(workspaceTitleBlock).toContain("display: flex;");
  });
});
