import type { ComponentProps } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
const mockUploadSpriteVoice = vi.fn();
const mockDeleteAllCharacterSprites = vi.fn();
const mockDeleteCharacter = vi.fn();
const mockDeleteCharacterMemory = vi.fn();
const mockDeleteCharacterSprite = vi.fn();
const mockDeleteSpriteVoice = vi.fn();
const mockExportCharacter = vi.fn();
const mockGenerateCharacterSetting = vi.fn();
const mockGetMem0Status = vi.fn();
const mockImportCharacters = vi.fn();
const mockInstallMissingRuntimeDependency = vi.fn();
const mockListCharacterMemories = vi.fn();
const mockOpenExternal = vi.fn();
const mockRememberCharacterMemory = vi.fn();
const mockSaveSpriteScale = vi.fn();
const mockSaveSpriteVoiceText = vi.fn();
const mockSaveSpriteVoiceType = vi.fn();
const mockTranslateCharacterFields = vi.fn();
const pickerState = vi.hoisted(() => ({ paths: [] as string[] }));

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
    PathPickerDialog: ({
      multiple,
      onClose,
      onSelect,
      onSelectMany,
      open,
      title,
    }: ComponentProps<typeof actual.PathPickerDialog>) => {
      if (!open) {
        return null;
      }
      const paths = pickerState.paths.length ? pickerState.paths : ["D:/packs/mika.char"];
      return (
        <div aria-label={title} role="dialog">
          <button
            onClick={() => {
              if (multiple) {
                onSelectMany?.(paths);
              } else {
                onSelect?.(paths[0]);
              }
              onClose();
            }}
            type="button"
          >
            Choose mocked paths
          </button>
        </div>
      );
    },
  };
});

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
}));

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
  openExternal: (url: string) => mockOpenExternal(url),
}));

vi.mock("../../../entities/chat/repository", () => ({
  installMissingRuntimeDependency: (...args: unknown[]) => mockInstallMissingRuntimeDependency(...args),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  deleteAllCharacterSprites: (name: string) => mockDeleteAllCharacterSprites(name),
  deleteCharacter: (name: string) => mockDeleteCharacter(name),
  deleteCharacterMemory: (name: string, memoryId: string) => mockDeleteCharacterMemory(name, memoryId),
  deleteCharacterSprite: (name: string, index: number) => mockDeleteCharacterSprite(name, index),
  deleteSpriteVoice: (name: string, index: number) => mockDeleteSpriteVoice(name, index),
  exportCharacter: (name: string) => mockExportCharacter(name),
  generateCharacterSetting: (input: unknown) => mockGenerateCharacterSetting(input),
  getMem0Status: () => mockGetMem0Status(),
  importCharacters: (paths: string[]) => mockImportCharacters(paths),
  listCharacterMemories: (name: string) => mockListCharacterMemories(name),
  listCharacters: () => mockListCharacters(),
  rememberCharacterMemory: (name: string, memory: string) => mockRememberCharacterMemory(name, memory),
  saveCharacter: (character: Character, originalName?: string) => mockSaveCharacter(character, originalName),
  saveCharacterEmotionTags: (name: string, emotionTags: string) => mockSaveCharacterEmotionTags(name, emotionTags),
  saveSpriteScale: (name: string, scale: number) => mockSaveSpriteScale(name, scale),
  saveSpriteVoiceText: (name: string, index: number, text: string) => mockSaveSpriteVoiceText(name, index, text),
  saveSpriteVoiceType: (name: string, index: number, voiceType: string) =>
    mockSaveSpriteVoiceType(name, index, voiceType),
  translateCharacterFields: (input: unknown) => mockTranslateCharacterFields(input),
  uploadCharacterSprites: (input: unknown) => mockUploadCharacterSprites(input),
  uploadSpriteVoice: (input: unknown) => mockUploadSpriteVoice(input),
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
    pickerState.paths = [];
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    mockGetAppConfig.mockResolvedValue(structuredClone(sampleConfig));
    mockListCharacters.mockResolvedValue([structuredClone(character)]);
    mockDeleteAllCharacterSprites.mockImplementation(async (name: string) => ({
      ...structuredClone(character),
      emotion_tags: "",
      name,
      sprites: [],
    }));
    mockDeleteCharacter.mockResolvedValue(undefined);
    mockDeleteCharacterMemory.mockImplementation(async () => ({ count: 0, memories: [] }));
    mockDeleteCharacterSprite.mockImplementation(async (name: string, index: number) => ({
      ...structuredClone(character),
      name,
      sprites: [
        { path: "D:/sprites/mika/sprite-a.png", voice_path: "D:/voices/mika.wav", voice_text: "hello" },
        { path: "D:/sprites/mika/sprite-b.png" },
      ].filter((_, spriteIndex) => spriteIndex !== index),
    }));
    mockDeleteSpriteVoice.mockImplementation(async (name: string, index: number) => ({
      ...structuredClone(character),
      name,
      sprites: [
        {
          path: "D:/sprites/mika/sprite-a.png",
          voice_path: index === 0 ? "" : "D:/voices/mika.wav",
          voice_text: index === 0 ? "" : "hello",
        },
      ],
    }));
    mockExportCharacter.mockResolvedValue("D:/exports/Mika.char");
    mockGenerateCharacterSetting.mockResolvedValue({
      characterSetting: "Generated setting.",
      message: "Generated",
    });
    mockGetMem0Status.mockResolvedValue({ status: "ready" });
    mockImportCharacters.mockImplementation(async (paths: string[]) =>
      paths.map((path, index) => ({
        ...structuredClone(character),
        name: index === 0 ? "Imported Mika" : `Imported ${index + 1}`,
        sprite_prefix: path,
      })),
    );
    mockInstallMissingRuntimeDependency.mockResolvedValue(undefined);
    mockListCharacterMemories.mockResolvedValue({
      count: 1,
      memories: [{ id: "memory-1", memory: "Likes tea" }],
    });
    mockOpenExternal.mockResolvedValue(undefined);
    mockRememberCharacterMemory.mockImplementation(async (_name: string, memory: string) => ({
      count: 2,
      memories: [
        { id: "memory-1", memory: "Likes tea" },
        { id: "memory-2", memory },
      ],
    }));
    mockSaveCharacter.mockImplementation(async (input: Character) => input);
    mockSaveCharacterEmotionTags.mockImplementation(async (_name: string, emotionTags: string) => ({
      ...character,
      emotion_tags: emotionTags,
    }));
    mockSaveSpriteScale.mockImplementation(async (name: string, scale: number) => ({
      ...structuredClone(character),
      name,
      sprite_scale: scale,
    }));
    mockSaveSpriteVoiceText.mockImplementation(async (name: string, index: number, text: string) => ({
      ...structuredClone(character),
      name,
      sprites: [{ ...character.sprites[index], voice_path: "D:/voices/mika.wav", voice_text: text }],
    }));
    mockSaveSpriteVoiceType.mockResolvedValue(undefined);
    mockTranslateCharacterFields.mockResolvedValue({
      characterSetting: "Translated setting.",
      emotionTags: "Sprite 1: smile\n",
      name: "Mika Translated",
    });
    mockUploadCharacterSprites.mockImplementation(async (input: { name: string; paths: string[] }) => ({
      ...character,
      name: input.name,
      sprites: input.paths.map((path) => ({ path })),
    }));
    mockUploadSpriteVoice.mockImplementation(async (input: { voiceType?: "preset" | "reference" }) => ({
      ...character,
      sprites: [{ ...character.sprites[0], voice_path: "D:/new/sora.wav", voice_type: input.voiceType }],
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
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

  it("uploads sprite voice with the displayed default preset type", async () => {
    renderPage();

    await screen.findByDisplayValue("Mika");
    fireEvent.click(screen.getByRole("button", { name: "Voice upload file" }));
    fireEvent.click(screen.getByRole("button", { name: "Upload voice" }));

    await waitFor(() =>
      expect(mockUploadSpriteVoice).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Mika",
          spriteIndex: 0,
          voicePath: "D:/new/sora.wav",
          voiceType: "preset",
        }),
      ),
    );
  });

  it("keeps sprite voice uploads preset when GPT-SoVITS models have no sprite voice text", async () => {
    mockListCharacters.mockResolvedValue([
      {
        ...structuredClone(character),
        gpt_model_path: "D:/models/mika.ckpt",
        sovits_model_path: "D:/models/mika.pth",
      },
    ]);
    renderPage();

    await screen.findByDisplayValue("Mika");
    expect(screen.getByRole("radio", { name: "Preset voice" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Voice upload file" }));
    fireEvent.click(screen.getByRole("button", { name: "Upload voice" }));

    await waitFor(() =>
      expect(mockUploadSpriteVoice).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Mika",
          spriteIndex: 0,
          voicePath: "D:/new/sora.wav",
          voiceType: "preset",
        }),
      ),
    );
  });

  it("defaults sprite voice uploads to reference when GPT-SoVITS models have sprite voice text", async () => {
    mockListCharacters.mockResolvedValue([
      {
        ...structuredClone(character),
        gpt_model_path: "D:/models/mika.ckpt",
        sovits_model_path: "D:/models/mika.pth",
        sprites: [{ ...character.sprites[0], voice_text: "Reference line" }],
      },
    ]);
    renderPage();

    await screen.findByDisplayValue("Mika");
    expect(screen.getByRole("radio", { name: "Reference voice (requires validation)" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Voice upload file" }));
    fireEvent.click(screen.getByRole("button", { name: "Upload voice" }));

    await waitFor(() =>
      expect(mockUploadSpriteVoice).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Mika",
          spriteIndex: 0,
          voicePath: "D:/new/sora.wav",
          voiceType: "reference",
        }),
      ),
    );
  });

  it("imports and exports packages, opens resources, and runs AI actions", async () => {
    renderPage();

    await screen.findByDisplayValue("Mika");
    fireEvent.click(screen.getByRole("button", { name: "Community characters" }));
    fireEvent.click(screen.getByRole("button", { name: "Upload contribution" }));
    expect(mockOpenExternal).toHaveBeenCalledTimes(2);

    pickerState.paths = ["D:/packs/mika.char", "D:/packs/sora.cha"];
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Import" })).getByText("Choose mocked paths"));
    await waitFor(() => expect(mockImportCharacters).toHaveBeenCalledWith(pickerState.paths));

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(mockExportCharacter).toHaveBeenCalledWith("Imported 2"));

    fireEvent.click(screen.getByRole("button", { name: "AI write" }));
    await waitFor(() =>
      expect(mockGenerateCharacterSetting).toHaveBeenCalledWith({ name: "Mika", setting: "Quiet student." }),
    );
    await waitFor(() => expect(screen.getByLabelText("Character setting")).toHaveValue("Generated setting."));

    fireEvent.click(screen.getByRole("button", { name: "AI translate" }));
    await waitFor(() =>
      expect(mockTranslateCharacterFields).toHaveBeenCalledWith({
        characterSetting: "Generated setting.",
        emotionTags: "Sprite 1: happy\n",
        name: "Mika",
      }),
    );
    await waitFor(() => expect(screen.getByLabelText("Character name")).toHaveValue("Mika Translated"));
  });

  it("saves sprite metadata and confirms sprite resource deletion", async () => {
    mockListCharacters.mockResolvedValue([
      {
        ...structuredClone(character),
        sprites: [
          { path: "D:/sprites/mika/sprite-a.png", voice_path: "D:/voices/mika.wav", voice_text: "hello" },
          { path: "D:/sprites/mika/sprite-b.png" },
        ],
      },
    ]);
    renderPage();

    await screen.findByDisplayValue("Mika");
    fireEvent.change(screen.getByLabelText("Display scale"), { target: { value: "1.25" } });
    fireEvent.click(screen.getByRole("button", { name: "Save scale" }));
    await waitFor(() => expect(mockSaveSpriteScale).toHaveBeenCalledWith("Mika", 1.25));

    fireEvent.click(screen.getByRole("radio", { name: "Reference voice (requires validation)" }));
    await waitFor(() => expect(mockSaveSpriteVoiceType).toHaveBeenCalledWith("Mika", 0, "reference"));

    const voiceTextInput = screen.getByDisplayValue("hello");
    fireEvent.change(voiceTextInput, { target: { value: "updated line" } });
    fireEvent.blur(voiceTextInput);
    await waitFor(() => expect(mockSaveSpriteVoiceText).toHaveBeenCalledWith("Mika", 0, "updated line"));

    fireEvent.click(screen.getByRole("button", { name: "Delete voice" }));
    let dialog = screen.getByRole("dialog", { name: "Delete voice" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(mockDeleteSpriteVoice).toHaveBeenCalledWith("Mika", 0));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Delete voice" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    dialog = screen.getByRole("dialog", { name: "Remove" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(mockDeleteCharacterSprite).toHaveBeenCalledWith("Mika", 0));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Remove" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Delete all sprites" }));
    dialog = screen.getByRole("dialog", { name: "Delete all sprites" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDeleteAllCharacterSprites).toHaveBeenCalledWith("Mika"));
  });

  it("refreshes, adds, and deletes long-term memories", async () => {
    renderPage();

    await screen.findByDisplayValue("Mika");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(mockGetMem0Status).toHaveBeenCalled());
    expect(await screen.findByText("Likes tea")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Memory content"), { target: { value: "Enjoys rain" } });
    fireEvent.click(screen.getByRole("button", { name: "Add memory" }));
    await waitFor(() => expect(mockRememberCharacterMemory).toHaveBeenCalledWith("Mika", "Enjoys rain"));
    expect(await screen.findByText("Enjoys rain")).toBeInTheDocument();

    const memoryRow = screen.getByText("Likes tea").closest(".memory-row");
    expect(memoryRow).toBeInstanceOf(HTMLElement);
    fireEvent.click(within(memoryRow as HTMLElement).getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDeleteCharacterMemory).toHaveBeenCalledWith("Mika", "memory-1"));
  });

  it("confirms deleting the selected character", async () => {
    renderPage();

    await screen.findByDisplayValue("Mika");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete character" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockDeleteCharacter).toHaveBeenCalledWith("Mika"));
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

  it("blocks invalid unsaved character actions before calling repositories", async () => {
    mockListCharacters.mockResolvedValue([]);
    renderPage();

    const nameInput = await screen.findByLabelText("Character name");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Validation failed")).toBeInTheDocument();
    expect(mockSaveCharacter).not.toHaveBeenCalled();

    fireEvent.change(nameInput, { target: { value: "Sora" } });
    fireEvent.change(screen.getByLabelText("Upload directory name (ASCII)"), { target: { value: "空" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Sprite directory must contain ASCII characters only/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(screen.getAllByText("Choose images...").length).toBeGreaterThan(1));
    expect(mockUploadCharacterSprites).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Save scale" }));
    await waitFor(() => expect(screen.getAllByText("Save scale").length).toBeGreaterThan(1));
    expect(mockSaveSpriteScale).not.toHaveBeenCalled();

    expect(mockSaveCharacterEmotionTags).not.toHaveBeenCalled();
    expect(mockUploadSpriteVoice).not.toHaveBeenCalled();
  });

  it("surfaces missing memory dependencies and installs them with task progress", async () => {
    mockGetMem0Status.mockResolvedValueOnce({ status: "missing_dependency" });
    mockListCharacterMemories.mockResolvedValueOnce({
      kind: "missing_dependency",
      moduleName: "mem0",
      packageName: "mem0ai",
    });
    mockInstallMissingRuntimeDependency.mockImplementation(
      async (_input, options?: { onTaskUpdate?: (task: unknown) => void }) => {
        options?.onTaskUpdate?.({
          done: false,
          id: "task-1",
          logs: ["Installing mem0ai"],
          status: "running",
        });
        return { message: "installed" };
      },
    );

    renderPage();

    await screen.findByDisplayValue("Mika");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Missing Python dependency")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() =>
      expect(mockInstallMissingRuntimeDependency).toHaveBeenCalledWith(
        { moduleName: "mem0" },
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
    await waitFor(() => expect(mockListCharacterMemories).toHaveBeenCalledTimes(2));
  });
});
