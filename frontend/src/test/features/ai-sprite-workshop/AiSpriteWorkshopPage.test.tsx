import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiSpriteWorkshopPage } from "../../../features/ai-sprite-workshop/AiSpriteWorkshopPage";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { AppConfig } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mocks = {
  generateSpriteImage: vi.fn(),
  generateSpritePrompts: vi.fn(),
  getAppConfig: vi.fn(),
  listCharacters: vi.fn(),
  registerGeneratedCharacterSprites: vi.fn(),
};

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mocks.getAppConfig(),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: () => mocks.listCharacters(),
  registerGeneratedCharacterSprites: (input: unknown) => mocks.registerGeneratedCharacterSprites(input),
}));

vi.mock("../../../entities/tools/repository", () => ({
  generateSpriteImage: (input: unknown, options: unknown) => mocks.generateSpriteImage(input, options),
  generateSpritePrompts: (input: unknown, options: unknown) => mocks.generateSpritePrompts(input, options),
}));

function readyConfig(): AppConfig {
  return {
    api_config: {
      llm_provider: "OpenAI",
      t2i_api_url: "http://127.0.0.1:8188",
      t2i_default_workflow_path: "D:/workflows/sprite.json",
      t2i_provider: "comfyui",
    },
    background_list: [],
    characters: [],
    system_config: {},
  } as unknown as AppConfig;
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nProvider language="en">
        <ToastProvider>
          <MemoryRouter
            future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
            initialEntries={["/settings/ai-sprites?character=Mika"]}
          >
            <AiSpriteWorkshopPage />
          </MemoryRouter>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("AiSpriteWorkshopPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getAppConfig.mockResolvedValue(readyConfig());
    mocks.registerGeneratedCharacterSprites.mockResolvedValue({
      ...createCharacter(),
      emotion_tags: "立绘 1：smile, hand wave\n",
      name: "Mika",
      sprites: [{ path: "data/sprite/mika/ai_smile.png" }],
    });
    mocks.generateSpriteImage.mockResolvedValue({
      file: "data/sprite/mika/ai_smile.png",
      files: ["data/sprite/mika/ai_smile.png"],
      message: "Sprite generated.",
      outputDir: "data/sprite/mika",
    });
    mocks.generateSpritePrompts.mockResolvedValue({
      items: [
        {
          label: "smile, hand wave",
          prompt:
            "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, anime visual novel sprite, Mika, hand wave, character name: Mika",
        },
        {
          label: "serious, upright pose",
          prompt:
            "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, anime visual novel sprite, Mika, upright pose, character name: Mika",
        },
        {
          label: "surprised, hand gesture",
          prompt:
            "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, anime visual novel sprite, Mika, hand gesture, character name: Mika",
        },
        {
          label: "calm, relaxed pose",
          prompt:
            "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, anime visual novel sprite, Mika, relaxed pose, character name: Mika",
        },
      ],
      prompts: [],
    });
    mocks.listCharacters.mockResolvedValue([
      {
        ...createCharacter(),
        character_setting: "Quiet student, \u6e29\u67d4\u4f46\u52c7\u6562\u3002",
        name: "Mika",
      },
    ]);
  });

  it("creates editable sprite labels and SD prompts only after clicking generate", async () => {
    renderPage();

    expect(await screen.findByText("No prompt candidates yet")).toBeInTheDocument();
    expect(screen.queryByText("Sprite 1")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Positive prompt reference"), {
      target: { value: "anime key visual, detailed eyes, soft rim lighting" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate prompts" }));

    expect(await screen.findByText("Sprite 1")).toBeInTheDocument();
    expect(mocks.generateSpritePrompts).toHaveBeenCalledWith(
      {
        characterName: "Mika",
        composition: "thigh_up",
        count: 4,
        language: "en",
        positivePromptReference: "anime key visual, detailed eyes, soft rim lighting",
      },
      undefined,
    );
    expect(screen.getByDisplayValue("smile, hand wave")).toBeInTheDocument();
    const prompts = screen.getAllByDisplayValue(/character name: Mika/) as HTMLTextAreaElement[];
    expect(prompts).toHaveLength(4);
    prompts.forEach((prompt) => {
      expect(prompt.value).toMatch(/^[\x20-\x7E]+$/);
      expect(prompt.value).toMatch(/^masterpiece, best quality, highres, official art, solo, 1 person, single character/);
      expect(prompt.value).toContain("official art");
      expect(prompt.value).toContain("clean lineart");
      expect(prompt.value).toContain("single view");
      expect(prompt.value).toContain("anime visual novel sprite");
    });
    expect(screen.getByText("Generated 4 prompt candidate(s).")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Generate sprite" })[0]);

    expect(await screen.findByRole("button", { name: "Retry image" })).toBeInTheDocument();
    expect(screen.getByAltText("smile, hand wave")).toHaveAttribute("src", expect.stringMatching(/[?&]v=\d+/));
    expect(mocks.generateSpriteImage).toHaveBeenCalledWith(
      {
        characterName: "Mika",
        label: "smile, hand wave",
        negativePrompt:
          "low quality, blurry, extra limbs, text, watermark, multiple views, multiple angles, turnaround, character sheet, reference sheet, expression sheet, pose sheet, multiple panels, collage",
        prompt:
          "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, anime visual novel sprite, Mika, hand wave, character name: Mika",
      },
      expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Add to character" }));

    expect(await screen.findAllByText("Added 1 sprite(s) to the character sprite list.")).toHaveLength(2);
    expect(mocks.registerGeneratedCharacterSprites).toHaveBeenCalledWith({
      items: [{ label: "smile, hand wave", path: "data/sprite/mika/ai_smile.png" }],
      name: "Mika",
    });
  });
});
