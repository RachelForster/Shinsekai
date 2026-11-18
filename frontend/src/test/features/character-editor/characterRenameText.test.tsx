import type { ComponentProps } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CharacterEditorPage } from "../../../features/character-editor/CharacterEditorPage";
import {
  buildCharacterNameMatchPattern,
  previewCharacterRenameText,
} from "../../../features/character-editor/characterRenameText";
import type { Character } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { SELF_PERSONA_ID, SELF_PERSONA_SPRITE_PREFIX } from "../../../shared/playerCharacterOptions";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const mockGetAppConfig = vi.fn();
const mockListCharacters = vi.fn();
const mockSaveCharacter = vi.fn();

vi.mock("../../../shared/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/ui")>();
  return {
    ...actual,
    FilePicker: ({ value, pickLabel }: { value?: string; pickLabel?: string }) => (
      <button type="button">{value || pickLabel || "Choose file"}</button>
    ),
    PathPickerDialog: ({ open, title }: ComponentProps<typeof actual.PathPickerDialog>) =>
      open ? <div aria-label={title} role="dialog" /> : null,
  };
});

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
}));

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
  openExternal: vi.fn(),
}));

vi.mock("../../../entities/chat/repository", () => ({
  installMissingRuntimeDependency: vi.fn(),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  autoGroupCharacterSprites: vi.fn(),
  awakenCharacterMemory: vi.fn(),
  deleteAllCharacterSprites: vi.fn(),
  deleteCharacter: vi.fn(),
  deleteCharacterMemories: vi.fn(),
  deleteCharacterMemory: vi.fn(),
  deleteCharacterSprite: vi.fn(),
  deleteSpriteVoice: vi.fn(),
  exportCharacter: vi.fn(),
  exportCharacterMemories: vi.fn(),
  generateCharacterSetting: vi.fn(),
  getMem0Status: () => Promise.resolve({ status: "ready" }),
  importCharacters: vi.fn(),
  importGeneratedCharacterSprites: vi.fn(),
  listCharacterMemories: () => Promise.resolve({ count: 0, memories: [] }),
  listCharacters: () => mockListCharacters(),
  pinCharacterMemory: vi.fn(),
  planCharacterSprites: vi.fn(),
  rememberCharacterMemory: vi.fn(),
  renderCharacterSprite: vi.fn(),
  saveCharacter: (character: Character, originalName?: string) => mockSaveCharacter(character, originalName),
  saveCharacterEmotionTags: vi.fn(),
  saveCharacterSpriteGroups: vi.fn(),
  saveSpriteVoiceText: vi.fn(),
  saveSpriteVoiceType: vi.fn(),
  searchCharacterMemories: vi.fn(),
  translateCharacterFields: vi.fn(),
  uploadCharacterSprites: vi.fn(),
  uploadSpriteVoice: vi.fn(),
}));

const selfBaseCharacter: Character = {
  avatar_type: "static",
  avatars: {},
  character_brief: "安杏栗子是一名喜欢黑咖啡的学生。",
  character_setting: "安杏栗子的背景信息：温柔沉静。\n安杏栗子擅长观星。",
  color: "#66ccff",
  emotion_tags: "Sprite 1: calm\n",
  gpt_model_path: "",
  id: SELF_PERSONA_ID,
  is_builtin: true,
  name: "安杏栗子",
  pinned: true,
  prompt_lang: "",
  prompt_text: "",
  pronunciation_map: {},
  refer_audio_path: "",
  sovits_model_path: "",
  speech_speed: 1,
  speech_volume: 1,
  sprite_prefix: SELF_PERSONA_SPRITE_PREFIX,
  sprite_scale: 1,
  sprites: [{ path: "D:/sprites/self/01.png" }],
  undeletable: true,
};

function renderPage(client: QueryClient) {
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

describe("characterRenameText helpers", () => {
  it("counts and replaces CJK names across setting and brief", () => {
    const preview = previewCharacterRenameText(
      {
        character_brief: "安杏栗子是一名学生。",
        character_setting: "安杏栗子的背景信息：温柔。\n喜欢咖啡的安杏栗子。",
      },
      "安杏栗子",
      "安杏浅羽",
    );
    expect(preview.settingMatches).toBe(2);
    expect(preview.briefMatches).toBe(1);
    expect(preview.totalMatches).toBe(3);
    expect(preview.nextSetting).toBe("安杏浅羽的背景信息：温柔。\n喜欢咖啡的安杏浅羽。");
    expect(preview.nextBrief).toBe("安杏浅羽是一名学生。");
  });

  it("applies ASCII word boundaries, case sensitivity, and literal replacement safety", () => {
    expect(buildCharacterNameMatchPattern("   ")).toBeNull();
    const boundaryPreview = previewCharacterRenameText(
      {
        character_brief: "An likes tea; an apple is unrelated.",
        character_setting: "An is calm. And Animation an stay untouched. An的背景。",
      },
      "An",
      "Bob",
    );
    expect(boundaryPreview.settingMatches).toBe(2);
    expect(boundaryPreview.briefMatches).toBe(1);
    expect(boundaryPreview.nextSetting).toBe("Bob is calm. And Animation an stay untouched. Bob的背景。");
    expect(boundaryPreview.nextBrief).toBe("Bob likes tea; an apple is unrelated.");

    const specialPreview = previewCharacterRenameText(
      { character_brief: "", character_setting: "A.B+ met A_B+" },
      "A.B+",
      "$&$1",
    );
    expect(specialPreview.settingMatches).toBe(1);
    expect(specialPreview.nextSetting).toBe("$&$1 met A_B+");

    const emptyPreview = previewCharacterRenameText(
      { character_brief: "Quiet", character_setting: "Quiet student." },
      "Mika",
      "Mika",
    );
    expect(emptyPreview.totalMatches).toBe(0);
  });
});

describe("CharacterEditorPage rename text confirmation dialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    mockGetAppConfig.mockResolvedValue(structuredClone(sampleConfig));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("prompts on rename when setting or brief contains old name and replaces text when confirmed", async () => {
    let serverChar = structuredClone(selfBaseCharacter);
    mockListCharacters.mockImplementation(async () => [structuredClone(serverChar)]);
    mockSaveCharacter.mockImplementation(async (input: Character) => {
      serverChar = structuredClone(input);
      return structuredClone(serverChar);
    });

    const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    renderPage(client);

    await waitFor(() => expect(screen.getByLabelText("Character name")).toHaveValue("安杏栗子"));

    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "安杏浅羽" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm: Character name" }));

    const dialog = await screen.findByRole("dialog", { name: "Update name in setting & brief?" });
    expect(dialog).toHaveTextContent('3 occurrence(s) of the old name "安杏栗子"');
    expect(mockSaveCharacter).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Replace & rename" }));

    await waitFor(() => expect(mockSaveCharacter).toHaveBeenCalledTimes(1));
    expect(mockSaveCharacter).toHaveBeenCalledWith(
      expect.objectContaining({
        character_brief: "安杏浅羽是一名喜欢黑咖啡的学生。",
        character_setting: "安杏浅羽的背景信息：温柔沉静。\n安杏浅羽擅长观星。",
        id: SELF_PERSONA_ID,
        name: "安杏浅羽",
      }),
      "安杏栗子",
    );

    await waitFor(() => expect(screen.getByLabelText("Character name")).toHaveValue("安杏浅羽"));
    expect(screen.getByLabelText("Character setting")).toHaveValue(
      "安杏浅羽的背景信息：温柔沉静。\n安杏浅羽擅长观星。",
    );
    expect(screen.getByLabelText("Character brief")).toHaveValue("安杏浅羽是一名喜欢黑咖啡的学生。");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["templates", "session"] });
  });

  it("supports keeping original text or cancelling without saving", async () => {
    let serverChar = structuredClone(selfBaseCharacter);
    mockListCharacters.mockImplementation(async () => [structuredClone(serverChar)]);
    mockSaveCharacter.mockImplementation(async (input: Character) => {
      serverChar = structuredClone(input);
      return structuredClone(serverChar);
    });

    const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
    renderPage(client);

    await waitFor(() => expect(screen.getByLabelText("Character name")).toHaveValue("安杏栗子"));

    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "安杏浅羽" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm: Character name" }));

    const firstDialog = await screen.findByRole("dialog", { name: "Update name in setting & brief?" });
    fireEvent.click(within(firstDialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Update name in setting & brief?" })).not.toBeInTheDocument(),
    );
    expect(mockSaveCharacter).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Character name")).toHaveValue("安杏浅羽");

    fireEvent.click(screen.getByRole("button", { name: "Confirm: Character name" }));
    const secondDialog = await screen.findByRole("dialog", { name: "Update name in setting & brief?" });
    fireEvent.click(within(secondDialog).getByRole("button", { name: "Rename only" }));

    await waitFor(() => expect(mockSaveCharacter).toHaveBeenCalledTimes(1));
    expect(mockSaveCharacter).toHaveBeenCalledWith(
      expect.objectContaining({
        character_brief: selfBaseCharacter.character_brief,
        character_setting: selfBaseCharacter.character_setting,
        name: "安杏浅羽",
      }),
      "安杏栗子",
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Character setting")).toHaveValue(selfBaseCharacter.character_setting),
    );
  });
});
