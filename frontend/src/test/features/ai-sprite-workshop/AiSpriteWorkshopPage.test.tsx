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
  generateSpritePrompts: vi.fn(),
  getAppConfig: vi.fn(),
  listCharacters: vi.fn(),
};

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mocks.getAppConfig(),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: () => mocks.listCharacters(),
}));

vi.mock("../../../entities/tools/repository", () => ({
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
    mocks.generateSpritePrompts.mockResolvedValue({
      items: [
        {
          label: "smile, hand wave",
          prompt:
            "masterpiece, best quality, anime visual novel sprite, Mika, full body, transparent background, hand wave, character name: Mika",
        },
        {
          label: "serious, upright pose",
          prompt:
            "masterpiece, best quality, anime visual novel sprite, Mika, full body, transparent background, upright pose, character name: Mika",
        },
        {
          label: "surprised, hand gesture",
          prompt:
            "masterpiece, best quality, anime visual novel sprite, Mika, full body, transparent background, hand gesture, character name: Mika",
        },
        {
          label: "calm, relaxed pose",
          prompt:
            "masterpiece, best quality, anime visual novel sprite, Mika, full body, transparent background, relaxed pose, character name: Mika",
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

    fireEvent.click(screen.getByRole("button", { name: "Generate prompts" }));

    expect(await screen.findByText("Sprite 1")).toBeInTheDocument();
    expect(mocks.generateSpritePrompts).toHaveBeenCalledWith(
      { characterName: "Mika", count: 4, language: "en" },
      undefined,
    );
    expect(screen.getByDisplayValue("smile, hand wave")).toBeInTheDocument();
    const prompts = screen.getAllByDisplayValue(/character name: Mika/) as HTMLTextAreaElement[];
    expect(prompts).toHaveLength(4);
    prompts.forEach((prompt) => {
      expect(prompt.value).toMatch(/^[\x20-\x7E]+$/);
      expect(prompt.value).toContain("anime visual novel sprite");
    });
    expect(screen.getByText("Generated 4 prompt candidate(s).")).toBeInTheDocument();
  });
});
