import type { ComponentProps } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CharacterEditorPage, mergeSprites } from "../../../features/character-editor/CharacterEditorPage";
import type { Character } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { sampleConfig } from "../../../shared/platform/sampleData";
import type { TemplateLaunchSession } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mockGetAppConfig = vi.fn();
const mockListCharacters = vi.fn();
const mockAutoGroupCharacterSprites = vi.fn();
const mockAwakenCharacterMemory = vi.fn();
const mockPinCharacterMemory = vi.fn();
const mockPlanCharacterSprites = vi.fn();
const mockRenderCharacterSprite = vi.fn();
const mockImportGeneratedCharacterSprites = vi.fn();
const mockSaveCharacter = vi.fn();
const mockSaveCharacterEmotionTags = vi.fn();
const mockSaveCharacterSpriteGroups = vi.fn();
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
const mockSearchCharacterMemories = vi.fn();
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
  autoGroupCharacterSprites: (input: unknown) => mockAutoGroupCharacterSprites(input),
  awakenCharacterMemory: (input: unknown) => mockAwakenCharacterMemory(input),
  planCharacterSprites: (...args: unknown[]) => mockPlanCharacterSprites(...args),
  renderCharacterSprite: (...args: unknown[]) => mockRenderCharacterSprite(...args),
  importGeneratedCharacterSprites: (...args: unknown[]) => mockImportGeneratedCharacterSprites(...args),
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
  pinCharacterMemory: (input: unknown) => mockPinCharacterMemory(input),
  rememberCharacterMemory: (...args: unknown[]) => mockRememberCharacterMemory(...args),
  searchCharacterMemories: (input: { limit?: number; name: string; query: string }) =>
    mockSearchCharacterMemories(input),
  saveCharacter: (character: Character, originalName?: string) => mockSaveCharacter(character, originalName),
  saveCharacterEmotionTags: (name: string, emotionTags: string) => mockSaveCharacterEmotionTags(name, emotionTags),
  saveCharacterSpriteGroups: (input: unknown) => mockSaveCharacterSpriteGroups(input),
  saveSpriteVoiceText: (name: string, index: number, text: string) => mockSaveSpriteVoiceText(name, index, text),
  saveSpriteVoiceType: (name: string, index: number, voiceType: string) =>
    mockSaveSpriteVoiceType(name, index, voiceType),
  translateCharacterFields: (input: unknown) => mockTranslateCharacterFields(input),
  uploadCharacterSprites: (input: unknown) => mockUploadCharacterSprites(input),
  uploadSpriteVoice: (input: unknown) => mockUploadSpriteVoice(input),
}));

const character: Character = {
  avatar_type: "static",
  avatars: {},
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

function renderPage(
  client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  }),
) {
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

async function waitForCharacterLoaded(name = "Mika") {
  await waitFor(() => expect(screen.getByLabelText("Character name")).toHaveValue(name));
}

describe("mergeSprites", () => {
  it("falls back to index only when rewritten paths keep the same list shape", () => {
    const current = {
      ...structuredClone(character),
      sprites: [
        {
          path: "D:/old/sprite-a.png",
          portrait_crop: { x: 0.3, y: 0.2, zoom: 2 },
          voice_type: "preset" as const,
        },
        { path: "D:/old/sprite-b.png", voice_type: "reference" as const },
      ],
    };

    const merged = mergeSprites([{ path: "D:/new/sprite-a.png" }, { path: "D:/new/sprite-b.png" }], current);
    expect(merged.map((sprite) => sprite.voice_type)).toEqual(["preset", "reference"]);
    expect(merged[0].portrait_crop).toEqual({ x: 0.3, y: 0.2, zoom: 2 });

    expect(mergeSprites([{ path: "D:/new/sprite-b.png" }], current).map((sprite) => sprite.voice_type)).toEqual([
      undefined,
    ]);
  });
});

describe("CharacterEditorPage", () => {
  it("adds generated sprites with tags without losing unsaved personality edits", async () => {
    mockPlanCharacterSprites.mockResolvedValue({ items: [{ prompt: "smile pose", tagging: "微笑" }] });
    mockRenderCharacterSprite.mockResolvedValue({
      name: "Mika",
      path: "new.png",
      taskId: "render-1",
      prompt: "smile pose",
      tagging: "微笑",
    });
    mockImportGeneratedCharacterSprites.mockResolvedValue({
      ...structuredClone(character),
      sprites: [...character.sprites, { path: "new.png" }],
      emotion_tags: "立绘 1：happy\n立绘 2：微笑\n",
    });
    renderPage();
    await screen.findByDisplayValue("Quiet student.");
    fireEvent.change(screen.getByLabelText("Character setting"), { target: { value: "My unsaved personality" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate sprites" }));
    fireEvent.click(screen.getByRole("button", { name: "Plan prompts and tags" }));
    await screen.findByDisplayValue("smile pose");
    expect(mockPlanCharacterSprites).toHaveBeenCalledWith(
      expect.objectContaining({ setting: "My unsaved personality" }),
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to collection (1)" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Add to collection (1)" }));
    await screen.findByText("Sprites added with tags saved");
    const closeGenerator = within(screen.getByRole("region", { name: "Generate sprites" })).getByRole("button", {
      name: "Close",
    });
    await waitFor(() => expect(closeGenerator).toBeEnabled());
    await new Promise((resolve) => setTimeout(resolve, 650));
    expect(mockSaveCharacter).not.toHaveBeenCalled();
    fireEvent.click(closeGenerator);
    expect(screen.getByLabelText("Character setting")).toHaveValue("My unsaved personality");
    expect(mockSaveCharacter).not.toHaveBeenCalled();
  });
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
    mockSearchCharacterMemories.mockResolvedValue({ agentId: "Mika", count: 0, memories: [] });
    mockSaveCharacter.mockImplementation(async (input: Character) => input);
    mockSaveCharacterEmotionTags.mockImplementation(async (_name: string, emotionTags: string) => ({
      ...character,
      emotion_tags: emotionTags,
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
    mockUploadSpriteVoice.mockImplementation(async (input: { voiceType?: "fallback" | "preset" | "reference" }) => ({
      ...character,
      sprites: [{ ...character.sprites[0], voice_path: "D:/new/sora.wav", voice_type: input.voiceType }],
    }));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("saves batch sprite tags when the dialog is confirmed", async () => {
    renderPage();

    await waitForCharacterLoaded();
    const batchTagsButton = screen.getByRole("button", { name: "Batch tags" });
    await waitFor(() => expect(batchTagsButton).toBeEnabled());
    fireEvent.click(batchTagsButton);

    const dialog = await screen.findByRole("dialog", { name: "Batch sprite tags" });
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
    expect(screen.getByLabelText(/Upload directory name \(ASCII\)/)).toHaveValue("sora");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockSaveCharacter).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Sora",
          sprite_prefix: "sora",
        }),
        undefined,
      ),
    );
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Current character" })).toHaveTextContent("Sora"));
  });

  it("updates the cached template selection and invalidates knowledge binding names when a character is renamed", async () => {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    const session = {
      background: "",
      effectNames: [],
      filenameStub: "Session",
      historyPath: "",
      initSpritePath: "",
      maxDialogItems: 0,
      maxSpeechChars: 0,
      characterPromptMode: "compact",
      primaryCharacters: ["Mika"],
      roomId: "",
      scenario: "",
      selectedCharacters: ["Mika", "B"],
      system: "",
      templateFileDropdown: "",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: true,
      useTranslation: false,
      voiceLanguage: "ja",
    } satisfies TemplateLaunchSession;
    client.setQueryData(["templates", "session"], session);
    const bindingKey = ["knowledge", "binding-names", "world"];
    client.setQueryData(bindingKey, { knowledge_id: "world", characterNames: ["Mika"] });
    renderPage(client);

    const nameInput = screen.getByLabelText("Character name");
    await waitFor(() => expect(nameInput).toHaveValue("Mika"));
    fireEvent.change(nameInput, { target: { value: "C" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm: Character name" }));

    await waitFor(() => expect(mockSaveCharacter).toHaveBeenCalledWith(expect.objectContaining({ name: "C" }), "Mika"));
    await waitFor(() =>
      expect(client.getQueryData<TemplateLaunchSession>(["templates", "session"])?.selectedCharacters).toEqual([
        "C",
        "B",
      ]),
    );
    expect(client.getQueryData<TemplateLaunchSession>(["templates", "session"])?.primaryCharacters).toEqual(["C"]);
    expect(client.getQueryState(bindingKey)?.isInvalidated).toBe(true);
  });

  it("auto-saves a new character before uploading sprites", async () => {
    mockListCharacters.mockResolvedValue([]);
    renderPage();

    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "Sora" } });
    fireEvent.change(screen.getByLabelText(/Upload directory name \(ASCII\)/), { target: { value: "sora" } });
    expect(screen.queryByText("Choose images or MP4 / WebM videos...")).not.toBeInTheDocument();
    pickerState.paths = ["D:/new/sora.png", "D:/new/sora.webm"];
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    const picker = screen.getByRole("dialog", { name: "Choose images or MP4 / WebM videos..." });
    expect(mockUploadCharacterSprites).not.toHaveBeenCalled();
    fireEvent.click(within(picker).getByRole("button", { name: "Choose mocked paths" }));

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
        paths: ["D:/new/sora.png", "D:/new/sora.webm"],
      }),
    );
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Current character" })).toHaveTextContent("Sora"));
  });

  it("uploads sprite voice with the displayed default fallback type", async () => {
    renderPage();

    await waitForCharacterLoaded();
    fireEvent.click(await screen.findByRole("button", { name: "Voice upload file" }));
    fireEvent.click(screen.getByRole("button", { name: "Upload voice" }));

    await waitFor(() =>
      expect(mockUploadSpriteVoice).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Mika",
          spriteIndex: 0,
          voicePath: "D:/new/sora.wav",
          voiceType: "fallback",
        }),
      ),
    );
  });

  it("keeps sprite voice uploads fallback when GPT-SoVITS models have no sprite voice text", async () => {
    mockListCharacters.mockResolvedValue([
      {
        ...structuredClone(character),
        gpt_model_path: "D:/models/mika.ckpt",
        sovits_model_path: "D:/models/mika.pth",
      },
    ]);
    renderPage();

    await waitForCharacterLoaded();
    expect(await screen.findByRole("radio", { name: "Fallback voice" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Voice upload file" }));
    fireEvent.click(screen.getByRole("button", { name: "Upload voice" }));

    await waitFor(() =>
      expect(mockUploadSpriteVoice).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Mika",
          spriteIndex: 0,
          voicePath: "D:/new/sora.wav",
          voiceType: "fallback",
        }),
      ),
    );
  });

  it("uploads sprite voice as preset after explicit selection", async () => {
    renderPage();

    await waitForCharacterLoaded();
    fireEvent.click(await screen.findByRole("radio", { name: "Preset voice" }));
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

    await waitForCharacterLoaded();
    expect(await screen.findByRole("radio", { name: "Reference voice" })).toBeChecked();
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

    await waitForCharacterLoaded();
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

    await waitForCharacterLoaded();
    expect(screen.queryByLabelText("Display scale")).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("radio", { name: "Reference voice" }));
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

  it("preserves unsaved sprite tags when another sprite is deleted", async () => {
    mockListCharacters.mockResolvedValue([
      {
        ...structuredClone(character),
        emotion_tags: "Sprite 1: first\nSprite 2: second\n",
        sprites: [{ path: "D:/sprites/mika/sprite-a.png" }, { path: "D:/sprites/mika/sprite-b.png" }],
      },
    ]);
    renderPage();

    await waitForCharacterLoaded();
    fireEvent.click(await screen.findByTitle("sprite-b.png"));
    fireEvent.change(screen.getByLabelText("Sprite tag"), { target: { value: "unsaved second edit" } });
    fireEvent.click(screen.getByTitle("sprite-a.png"));
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    const dialog = screen.getByRole("dialog", { name: "Remove" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(mockDeleteCharacterSprite).toHaveBeenCalledWith("Mika", 0));
    await waitFor(() => expect(screen.getByLabelText("Sprite tag")).toHaveValue("unsaved second edit"));
  });

  it("keeps sprite voice types aligned by path after deleting a sprite", async () => {
    const sprites = [
      {
        path: "D:/sprites/mika/sprite-a.png",
        voice_path: "D:/voices/a.wav",
        voice_type: "preset" as const,
      },
      {
        path: "D:/sprites/mika/sprite-b.png",
        voice_path: "D:/voices/b.wav",
        voice_type: "fallback" as const,
      },
      {
        path: "D:/sprites/mika/sprite-c.png",
        voice_path: "D:/voices/c.wav",
        voice_text: "reference line",
        voice_type: "reference" as const,
      },
    ];
    const originalCharacter = {
      ...structuredClone(character),
      emotion_tags: "Sprite 1: first\nSprite 2: second\nSprite 3: third\n",
      sprites,
    };
    const updatedCharacter = {
      ...originalCharacter,
      emotion_tags: "Sprite 1: second\nSprite 2: third\n",
      sprites: sprites.slice(1),
    };
    mockListCharacters.mockResolvedValueOnce([originalCharacter]).mockResolvedValue([updatedCharacter]);
    mockDeleteCharacterSprite.mockResolvedValue(updatedCharacter);
    renderPage();

    await waitForCharacterLoaded();
    expect(await screen.findByRole("radio", { name: "Preset voice" })).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    const dialog = screen.getByRole("dialog", { name: "Remove" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(mockDeleteCharacterSprite).toHaveBeenCalledWith("Mika", 0));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Remove" })).not.toBeInTheDocument());
    expect(screen.getByTitle("sprite-b.png")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("radio", { name: "Fallback voice" })).toBeChecked();

    fireEvent.click(screen.getByTitle("sprite-c.png"));
    expect(screen.getByRole("radio", { name: "Reference voice" })).toBeChecked();
  });

  it("refreshes, adds, and deletes long-term memories", async () => {
    renderPage();

    await waitForCharacterLoaded();
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
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    const catalogKey = ["knowledge", "instances", "", 1];
    const bindingKey = ["knowledge", "binding-names", "world"];
    client.setQueryData(catalogKey, { count: 1, instances: [] });
    client.setQueryData(bindingKey, { knowledge_id: "world", characterNames: ["Mika"] });
    client.setQueryData<TemplateLaunchSession>(["templates", "session"], {
      background: "",
      characterPromptMode: "compact",
      effectNames: [],
      filenameStub: "Session",
      historyPath: "",
      initSpritePath: "",
      maxDialogItems: 0,
      maxSpeechChars: 0,
      primaryCharacters: ["Mika"],
      roomId: "",
      scenario: "",
      selectedCharacters: ["Mika", "B"],
      system: "",
      templateFileDropdown: "",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: true,
      useTranslation: false,
      voiceLanguage: "ja",
    });
    renderPage(client);

    await waitForCharacterLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete character" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockDeleteCharacter).toHaveBeenCalledWith("Mika"));
    await waitFor(() => {
      const session = client.getQueryData<TemplateLaunchSession>(["templates", "session"]);
      expect(session?.selectedCharacters).toEqual(["B"]);
      expect(session?.primaryCharacters).toEqual([]);
      expect(session?.characterPromptMode).toBeUndefined();
    });
    expect(client.getQueryState(catalogKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(bindingKey)?.isInvalidated).toBe(true);
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

    await waitForCharacterLoaded();
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
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByText("Validation failed")).toBeInTheDocument();
    expect(mockSaveCharacter).not.toHaveBeenCalled();

    fireEvent.change(nameInput, { target: { value: "Sora" } });
    fireEvent.change(screen.getByLabelText(/Upload directory name \(ASCII\)/), { target: { value: "空" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findAllByText(/Sprite directory must contain ASCII characters only/)).not.toHaveLength(0);

    pickerState.paths = ["D:/new/sora.png"];
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    fireEvent.click(screen.getByRole("button", { name: "Choose mocked paths" }));
    expect(mockUploadCharacterSprites).not.toHaveBeenCalled();

    expect(mockSaveCharacterEmotionTags).not.toHaveBeenCalled();
    expect(mockUploadSpriteVoice).not.toHaveBeenCalled();
  });

  it("installs missing memory dependencies and starts memory loading", async () => {
    mockGetMem0Status
      .mockResolvedValueOnce({ status: "missing_dependency" })
      .mockResolvedValueOnce({ status: "ready" });
    mockListCharacterMemories
      .mockResolvedValueOnce({
        kind: "missing_dependency",
        moduleName: "mem0",
        packageName: "mem0ai",
      })
      .mockResolvedValueOnce({ agentId: "Mika", count: 0, memories: [] });
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

    await waitForCharacterLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Missing Python dependency")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() =>
      expect(mockInstallMissingRuntimeDependency).toHaveBeenCalledWith(
        { moduleName: "mem0" },
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
    await waitFor(() => expect(screen.queryByText("Missing Python dependency")).not.toBeInTheDocument());
    await waitFor(() => expect(mockGetMem0Status).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mockListCharacterMemories).toHaveBeenCalledTimes(2));
  });

  it("opens Portrait crop from the sprites section and saves portrait_crop without discarding unsaved draft edits", async () => {
    mockSaveCharacter.mockImplementation(async (saved: Character) => structuredClone(saved));

    renderPage();
    await waitForCharacterLoaded();

    fireEvent.change(screen.getByLabelText("Character setting"), {
      target: { value: "Unsaved personality text" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Avatar" }));
    const dialog = await screen.findByRole("dialog", { name: /Adjust portrait crop/i });
    const sliders = within(dialog).getAllByRole("slider");
    expect(sliders).toHaveLength(3);
    fireEvent.change(sliders[0], { target: { value: "0.35" } });
    fireEvent.change(sliders[1], { target: { value: "0.18" } });
    fireEvent.change(sliders[2], { target: { value: "2.4" } });

    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mockSaveCharacter).toHaveBeenCalledTimes(1));
    const [savedPayload, originalName] = mockSaveCharacter.mock.calls[0] as [Character, string];
    expect(originalName).toBe("Mika");
    expect(savedPayload.portrait_crop).toEqual({ x: 0.35, y: 0.18, zoom: 2.4 });
    expect(savedPayload.character_setting).toBe("Quiet student.");
    expect(screen.getByLabelText("Character setting")).toHaveValue("Unsaved personality text");
  });

  it("locks the sprite prefix, hides delete, and keeps built-in 自设 pinned first after saving", async () => {
    const selfPersona: Character = {
      ...character,
      character_setting: "Player persona bio",
      is_builtin: true,
      name: "自设",
      pinned: true,
      sprite_prefix: "__self__",
      sprites: [],
      undeletable: true,
    };
    mockListCharacters.mockResolvedValue([selfPersona, character]);
    mockSaveCharacter.mockImplementation(async (saved: Character) => structuredClone(saved));

    renderPage();
    expect(await screen.findByLabelText("Display name")).toHaveAttribute("placeholder", "自设");
    expect(screen.getByLabelText(/Upload directory name \(ASCII\)/)).toBeDisabled();
    expect(screen.getByText("Global Player Persona & Public Self-Memory")).toBeInTheDocument();
    const basicSection = document.getElementById("character-basic") as HTMLElement;
    expect(within(basicSection).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Character setting"), {
      target: { value: "Updated player bio" },
    });
    await waitFor(() => expect(mockSaveCharacter).toHaveBeenCalledTimes(1), { timeout: 2500 });

    // Built-in 自设 remains first in the character selector even after saving!
    fireEvent.click(screen.getByRole("combobox", { name: "Current character" }));
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["自设", "Mika"]);
  });
  it("auto-saves a display name for the built-in persona under its original ID", async () => {
    const id = "自设";
    mockListCharacters.mockResolvedValue([
      { ...structuredClone(character), name: id, sprite_prefix: "__self__", is_builtin: true, undeletable: true },
    ]);
    renderPage();
    const name = await screen.findByLabelText("Display name");
    expect(name).toBeEnabled();
    expect(screen.getByLabelText(/Upload directory name \(ASCII\)/)).toBeDisabled();
    fireEvent.change(name, { target: { value: "Robin" } });

    await waitFor(
      () =>
        expect(mockSaveCharacter).toHaveBeenCalledWith(
          expect.objectContaining({ name: id, display_name: "Robin", sprite_prefix: "__self__" }),
          id,
        ),
      { timeout: 2500 },
    );
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Current character" })).toHaveTextContent("Robin"));
  });

  it("auto-saves non-identity edits using committed identity while keeping unconfirmed rename isolated", async () => {
    mockListCharacters.mockResolvedValue([
      { ...structuredClone(character), id: "char-mika" },
      { ...structuredClone(character), id: "char-aki", name: "Aki", sprite_prefix: "aki" },
    ]);
    renderPage();

    const nameInput = await screen.findByLabelText("Character name");
    await waitFor(() => expect(nameInput).toHaveValue("Mika"));

    // Editing name alone does not auto-save; it reveals inline Confirm/Cancel
    fireEvent.change(nameInput, { target: { value: "HalfTypedName" } });
    expect(screen.getByRole("button", { name: "Confirm: Character name" })).toBeInTheDocument();

    // Editing character_setting auto-saves with committed name "Mika", keeping "HalfTypedName" local
    fireEvent.change(screen.getByLabelText("Character setting"), {
      target: { value: "Auto-saved student bio" },
    });
    await waitFor(
      () =>
        expect(mockSaveCharacter).toHaveBeenCalledWith(
          expect.objectContaining({
            id: "char-mika",
            character_setting: "Auto-saved student bio",
            name: "Mika",
            sprite_prefix: "mika",
          }),
          "Mika",
        ),
      { timeout: 2500 },
    );
    expect(nameInput).toHaveValue("HalfTypedName");

    // Escape cancels the unconfirmed rename back to "Mika"
    fireEvent.keyDown(nameInput, { key: "Escape" });
    expect(nameInput).toHaveValue("Mika");

    // Flushing pending auto-save immediately when switching character
    mockSaveCharacter.mockClear();
    fireEvent.change(screen.getByLabelText("Character setting"), {
      target: { value: "Flushed on switch" },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "Current character" }));
    fireEvent.click(screen.getByRole("option", { name: "Aki" }));
    await waitFor(() =>
      expect(mockSaveCharacter).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "char-mika",
          character_setting: "Flushed on switch",
          name: "Mika",
        }),
        "Mika",
      ),
    );

    // Clicking New generates non-colliding sprite_prefix and Cancel returns to Aki
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.getByLabelText(/Upload directory name \(ASCII\)/)).toHaveValue("char_1");
    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "星奈" } });
    expect(screen.getByLabelText(/Upload directory name \(ASCII\)/)).toHaveValue("char_1");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByLabelText("Character name")).toHaveValue("Aki"));
  });

  it("prevents ID leaks into New drafts, preserves concurrent edits during rename, and cancels auto-save on delete", async () => {
    let catalog: Character[] = [
      {
        ...structuredClone(character),
        id: "char-mika",
        relation_graph: {
          edges: [{ content: "trust", source: "Mika", target: "Aki", temperature: 7 }],
          nodes: [{ key: "Mika" }, { key: "Aki" }],
        },
      },
      { ...structuredClone(character), id: "char-aki", name: "Aki", sprite_prefix: "aki" },
    ];
    mockListCharacters.mockImplementation(async () => structuredClone(catalog));
    mockDeleteCharacter.mockImplementation(async (deletedName: string) => {
      catalog = catalog.filter((item) => item.name !== deletedName);
    });
    const upsertIntoCatalog = (saved: Character) => {
      const idx = catalog.findIndex((item) => item.id === saved.id || item.name === saved.name);
      if (idx >= 0) {
        catalog[idx] = structuredClone(saved);
      } else {
        catalog.push(structuredClone(saved));
      }
      return structuredClone(saved);
    };

    let resolveFlushedSave!: (saved: Character) => void;
    mockSaveCharacter.mockImplementationOnce(
      () =>
        new Promise<Character>((resolve) => {
          resolveFlushedSave = (saved) => resolve(upsertIntoCatalog(saved));
        }),
    );

    renderPage();
    await waitForCharacterLoaded("Mika");

    // 1. Edit Mika, click New (flushing Mika's save), then resolve Mika's save while in Create mode -> must NOT leak char-mika!
    fireEvent.change(screen.getByLabelText("Character setting"), {
      target: { value: "Outgoing bio before New" },
    });
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(mockSaveCharacter).toHaveBeenCalledTimes(1);
    expect(mockSaveCharacter.mock.calls[0]?.[0]).not.toHaveProperty("relation_graph");

    await act(async () => {
      resolveFlushedSave({
        ...structuredClone(character),
        id: "char-mika",
        character_setting: "Outgoing bio before New",
      });
    });

    mockSaveCharacter.mockImplementationOnce(async (saved: Character) =>
      upsertIntoCatalog({
        ...structuredClone(saved),
        id: "char-sora",
      }),
    );
    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "Sora" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(mockSaveCharacter).toHaveBeenCalledTimes(2));
    const [createdPayload, createdOriginalName] = mockSaveCharacter.mock.calls[1] as [Character, string | undefined];
    expect(createdOriginalName).toBeUndefined();
    expect(createdPayload).not.toHaveProperty("id");
    expect(createdPayload.name).toBe("Sora");

    // 2. While confirming name rename, sprite_prefix confirm is disabled and concurrent setting edits survive!
    await waitForCharacterLoaded("Sora");
    let resolveRename!: (saved: Character) => void;
    mockSaveCharacter.mockClear();
    mockSaveCharacter
      .mockImplementationOnce(
        () =>
          new Promise<Character>((resolve) => {
            resolveRename = (saved) => resolve(upsertIntoCatalog(saved));
          }),
      )
      .mockImplementation(async (saved: Character) =>
        upsertIntoCatalog({ ...structuredClone(saved), id: "char-sora" }),
      );

    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "Sora Renamed" } });
    fireEvent.change(screen.getByLabelText("Upload directory name (ASCII)"), { target: { value: "sora_v2" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm: Character name" }));

    await waitFor(() => expect(screen.getByRole("button", { name: /Confirm: Upload directory name/ })).toBeDisabled());
    fireEvent.change(screen.getByLabelText("Character setting"), {
      target: { value: "Typed while rename in flight" },
    });

    await act(async () => {
      resolveRename({
        ...structuredClone(character),
        id: "char-sora",
        character_setting: "",
        name: "Sora Renamed",
        sprite_prefix: "sora",
      });
    });
    await waitForCharacterLoaded("Sora Renamed");
    expect(screen.getByLabelText("Character setting")).toHaveValue("Typed while rename in flight");
    expect(screen.getByLabelText("Upload directory name (ASCII)")).toHaveValue("sora_v2");

    // Wait for auto-save of the concurrent character_setting edit to settle under "Sora Renamed"
    await waitFor(
      () =>
        expect(mockSaveCharacter).toHaveBeenCalledWith(
          expect.objectContaining({
            id: "char-sora",
            character_setting: "Typed while rename in flight",
            name: "Sora Renamed",
          }),
          "Sora Renamed",
        ),
      { timeout: 2500 },
    );

    // 3. Edit character_setting then immediately delete -> pending auto-save is cancelled and never resurrects!
    mockSaveCharacter.mockClear();
    fireEvent.change(screen.getByLabelText("Character setting"), {
      target: { value: "Should never save after delete" },
    });
    const basicSection = document.getElementById("character-basic") as HTMLElement;
    fireEvent.click(within(basicSection).getByRole("button", { name: "Delete" }));
    const deleteDialog = screen.getByRole("dialog", { name: "Delete character" });
    fireEvent.click(within(deleteDialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDeleteCharacter).toHaveBeenCalledWith("Sora Renamed"));
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(mockSaveCharacter).not.toHaveBeenCalled();
  });
});
