import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CharacterEditorPage } from "../../../features/character-editor/CharacterEditorPage";
import type { Character } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const mockGetAppConfig = vi.fn();
const mockListCharacters = vi.fn();
const mockSaveCharacter = vi.fn();
const mockSaveCharacterEmotionTags = vi.fn();
const mockUploadCharacterSprites = vi.fn();

vi.mock("../../../shared/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/ui")>();
  return {
    ...actual,
    FilePicker: ({
      disabled,
      onPathChange,
      onPathsChange,
      pickLabel,
      value,
    }: {
      disabled?: boolean;
      onPathChange?: (path: string) => void;
      onPathsChange?: (paths: string[]) => void;
      pickLabel?: string;
      value?: string;
    }) => (
      <button
        onClick={() => {
          if (onPathsChange) {
            onPathsChange(["D:/new/sora.png"]);
            return;
          }
          onPathChange?.("D:/new/sora.wav");
        }}
        disabled={disabled}
        type="button"
      >
        {value || pickLabel || "Choose file"}
      </button>
    ),
  };
});

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
}));

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  deleteAllCharacterSprites: vi.fn(),
  deleteCharacter: vi.fn(),
  deleteCharacterMemory: vi.fn(),
  deleteCharacterSprite: vi.fn(),
  deleteSpriteVoice: vi.fn(),
  exportCharacter: vi.fn(),
  generateCharacterSetting: vi.fn(),
  importCharacters: vi.fn(),
  listCharacterMemories: vi.fn(),
  listCharacters: () => mockListCharacters(),
  rememberCharacterMemory: vi.fn(),
  saveCharacter: (character: Character, originalName?: string) => mockSaveCharacter(character, originalName),
  saveCharacterEmotionTags: (name: string, emotionTags: string) => mockSaveCharacterEmotionTags(name, emotionTags),
  saveSpriteScale: vi.fn(),
  saveSpriteVoiceText: vi.fn(),
  translateCharacterFields: vi.fn(),
  uploadCharacterSprites: (input: unknown) => mockUploadCharacterSprites(input),
  uploadSpriteVoice: vi.fn(),
}));

const character: Character = {
  character_setting: "Quiet student.",
  color: "#66ccff",
  emotion_tags: "Sprite 1: happy\n",
  gpt_model_path: "",
  name: "Mika",
  prompt_lang: "",
  prompt_text: "",
  pronunciation_map: {},
  refer_audio_path: "",
  sovits_model_path: "",
  speech_speed: 1,
  speech_volume: 1,
  sprite_prefix: "mika",
  sprite_scale: 1,
  sprites: [{ path: "D:/sprites/mika/sprite-a.png" }],
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <CharacterEditorPage />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("CharacterEditorPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAppConfig.mockResolvedValue(structuredClone(sampleConfig));
    mockListCharacters.mockResolvedValue([structuredClone(character)]);
    mockSaveCharacter.mockImplementation(async (input: Character) => input);
    mockSaveCharacterEmotionTags.mockImplementation(async (_name: string, emotionTags: string) => ({
      ...character,
      emotion_tags: emotionTags,
    }));
    mockUploadCharacterSprites.mockImplementation(async (input: { name: string; paths: string[] }) => ({
      ...character,
      name: input.name,
      sprites: input.paths.map((path) => ({ path })),
    }));
  });

  it("saves batch sprite tags when the dialog is confirmed", async () => {
    renderPage();

    await screen.findByDisplayValue("Mika");
    fireEvent.click(screen.getByRole("button", { name: "Batch tags" }));

    const dialog = screen.getByRole("dialog", { name: "Batch sprite tags" });
    fireEvent.change(within(dialog).getByLabelText("Emotion tags (per upload / order)"), {
      target: { value: "Sprite 1: calm\n" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(mockSaveCharacterEmotionTags).toHaveBeenCalledWith("Mika", "Sprite 1: calm\n"));
  });

  it("creates a character when saving without an existing current character", async () => {
    mockListCharacters.mockResolvedValue([]);
    renderPage();

    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "Sora" } });
    fireEvent.change(screen.getByLabelText("Upload directory name (ASCII)"), { target: { value: "sora" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockSaveCharacter).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Sora",
          sprite_prefix: "sora",
        }),
        undefined,
      ),
    );
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveTextContent("Sora"));
  });

  it("auto-saves a new character before uploading sprites", async () => {
    mockListCharacters.mockResolvedValue([]);
    renderPage();

    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "Sora" } });
    fireEvent.change(screen.getByLabelText("Upload directory name (ASCII)"), { target: { value: "sora" } });
    fireEvent.click(screen.getByRole("button", { name: "Choose images..." }));
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() =>
      expect(mockSaveCharacter).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Sora",
          sprite_prefix: "sora",
        }),
        undefined,
      ),
    );
    await waitFor(() =>
      expect(mockUploadCharacterSprites).toHaveBeenCalledWith({
        emotionTags: "",
        name: "Sora",
        paths: ["D:/new/sora.png"],
      }),
    );
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveTextContent("Sora"));
  });

  it("locks cloud voice reference controls when Kaggle GPT-SoVITS is selected", async () => {
    mockGetAppConfig.mockResolvedValue({
      ...structuredClone(sampleConfig),
      api_config: {
        ...sampleConfig.api_config,
        tts_provider: "kaggle-gpt-sovits",
      },
    });

    renderPage();

    await screen.findByDisplayValue("Mika");
    expect(screen.getByText(/Upload the \.char package in the Kaggle Notebook/)).toBeInTheDocument();
    const voiceReferencePickers = [
      screen.getByRole("button", { name: "GPT model path" }),
      screen.getByRole("button", { name: "SoVITS model" }),
      screen.getByRole("button", { name: "Reference audio" }),
    ];

    for (const picker of voiceReferencePickers) {
      expect(picker).toBeDisabled();
    }
    expect(screen.getByRole("textbox", { name: "Language (en/ja/zh)" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Reference line text" })).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: "TTS Speed" })).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: "TTS Volume" })).not.toBeDisabled();
  });
});
