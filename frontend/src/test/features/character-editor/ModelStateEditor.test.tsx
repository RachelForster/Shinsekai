import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Character } from "../../../entities/config/types";
import type { AvatarSession } from "../../../entities/character-visual/contracts";
import l2dFormat from "../../../entities/character-visual/adapters/l2d/format";
import { clearRegisteredAvatarFormats, registerAvatarFormat } from "../../../entities/character-visual/registry";
import { ModelStateEditor } from "../../../features/character-editor/ModelStateEditor";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import type { ShinsekaiPlatform } from "../../../shared/platform/types";

const pickPath = vi.hoisted(() => vi.fn());
vi.mock("../../../shared/desktop/desktopApi", () => ({
  isTauriDesktop: () => true,
  pickDesktopNativePath: pickPath,
}));

const neutral = { parameters: {}, expressions: [], motion: "" };
let state: unknown;
let session: AvatarSession<unknown, unknown>;
let character: Character;
const importModel = vi.fn();
const saveModelState = vi.fn();
const modelUrl = vi.fn((_model: string, path: string) => `http://localhost/api/avatar/file?path=${path}`);
const fetchState = vi.fn();

function view(draft = character, language: "en" | "zh_CN" = "en") {
  const onChange = vi.fn();
  const onSaved = vi.fn();
  const rendered = render(
    <I18nProvider language={language}>
      <ModelStateEditor character={draft} onChange={onChange} onSaved={onSaved} />
    </I18nProvider>,
  );
  return { ...rendered, onChange, onSaved };
}

beforeEach(() => {
  vi.clearAllMocks();
  character = {
    ...structuredClone(sampleConfig.characters[0]),
    avatar_type: "l2d",
    avatars: { l2d: { model_path: "", sprites: [], emotion_tags: "" } },
  };
  state = structuredClone(neutral);
  session = {
    capabilities: l2dFormat.capabilities,
    controls: {},
    apply: vi.fn(async (next) => {
      state = next;
    }),
    readState: () => state,
    resize: vi.fn(),
    setMouthOpen: vi.fn(),
    dispose: vi.fn(),
  };
  registerAvatarFormat({ ...l2dFormat, load: async () => ({ create: async () => session, Editor: () => null }) });
  window.__SHINSEKAI_IPC__ = {
    characters: { importModel, saveModelState },
    files: { modelUrl },
  } as unknown as ShinsekaiPlatform;
  pickPath.mockResolvedValue(["C:/models/haru.model3.json"]);
  importModel.mockResolvedValue(character);
  saveModelState.mockResolvedValue(character);
  fetchState.mockResolvedValue({ ok: true, json: async () => neutral });
  vi.stubGlobal("fetch", fetchState);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  cleanup();
  clearRegisteredAvatarFormats();
  delete window.__SHINSEKAI_IPC__;
  vi.unstubAllGlobals();
});

describe("ModelStateEditor shared controls and repositories", () => {
  it("uses the shared dropdown and preserves other banks when changing format", () => {
    const draft = {
      ...character,
      avatar_type: "static",
      avatars: { future: { model_path: "future.model", sprites: [], emotion_tags: "keep" } },
    };
    const { onChange } = view(draft);
    const select = screen.getByRole("combobox", { name: "Avatar format" });
    expect(select.tagName).toBe("BUTTON");
    fireEvent.click(select);
    fireEvent.click(screen.getByRole("option", { name: "Live2D Cubism" }));
    expect(onChange).toHaveBeenCalledWith({
      ...draft,
      avatar_type: "l2d",
      avatars: { ...draft.avatars, l2d: l2dFormat.createEmpty() },
    });
  });

  it("preserves an unavailable format and lets the user return to static", () => {
    const draft = {
      ...character,
      avatar_type: "future",
      avatars: { future: { model_path: "future.model", sprites: [], emotion_tags: "keep" } },
    };
    const { onChange } = view(draft);
    const select = screen.getByRole("combobox", { name: "Avatar format" });
    expect(select).toHaveTextContent("future: Unavailable");
    expect(screen.queryByRole("button", { name: "Import model" })).not.toBeInTheDocument();
    fireEvent.click(select);
    expect(screen.getByRole("option", { name: "future: Unavailable" })).toBeDisabled();
    fireEvent.click(screen.getByRole("option", { name: "Static sprites" }));
    expect(onChange).toHaveBeenCalledWith({ ...draft, avatar_type: "static" });
  });

  it("selects the entry through FilePicker's native path flow and imports via the character repository", async () => {
    const { onSaved } = view();
    expect(screen.getByRole("button", { name: "Import model" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Choose file" }));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Model entry" })).toHaveValue("C:/models/haru.model3.json"),
    );
    expect(pickPath).toHaveBeenCalledWith(
      expect.objectContaining({ extensions: [".model3.json"], mode: "file", multiple: false }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Import model" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(character));
    expect(importModel).toHaveBeenCalledWith({
      name: character.name,
      avatar_type: "l2d",
      source_path: "C:/models/haru.model3.json",
    });
  });

  it("uses another format's filters instead of assuming Live2D", async () => {
    registerAvatarFormat({
      ...l2dFormat,
      id: "demo",
      label: "Demo",
      modelExtensions: [".vrm"],
      load: async () => ({ create: async () => session, Editor: () => null }),
    });
    pickPath.mockResolvedValue(["C:/models/demo.vrm"]);
    view({ ...character, avatar_type: "demo" });
    fireEvent.click(screen.getByRole("button", { name: "Choose file" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Model entry" })).toHaveValue("C:/models/demo.vrm"));
    expect(pickPath).toHaveBeenCalledWith(expect.objectContaining({ extensions: [".vrm"] }));
  });

  it("retains manual path entry and does not import after cancelling the picker", async () => {
    pickPath.mockResolvedValue(null);
    view();
    fireEvent.click(screen.getByRole("button", { name: "Choose file" }));
    await waitFor(() => expect(pickPath).toHaveBeenCalledOnce());
    expect(importModel).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Model entry" }), {
      target: { value: "C:/models/manual.model3.json" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import model" }));
    await waitFor(() =>
      expect(importModel).toHaveBeenCalledWith(
        expect.objectContaining({ source_path: "C:/models/manual.model3.json" }),
      ),
    );
  });

  it("selects, loads and saves an existing state without changing its bank or index", async () => {
    character.avatars.l2d = {
      model_path: "C:\\models\\haru.model3.json",
      sprites: [{ path: "C:\\models\\states\\happy.json" }],
      emotion_tags: "Sprite 1: happy\n",
    };
    const savedState = { ...neutral, parameters: { ParamAngleX: 10 } };
    fetchState.mockResolvedValue({ ok: true, json: async () => savedState });
    const { onSaved } = view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Save state" })).toBeEnabled());
    expect(modelUrl).toHaveBeenCalledWith(character.avatars.l2d.model_path, "haru.model3.json");
    fireEvent.click(screen.getByRole("combobox", { name: "Model state" }));
    fireEvent.click(screen.getByRole("option", { name: "1: happy.json" }));
    await waitFor(() => expect(session.apply).toHaveBeenCalledWith(savedState, "edit", expect.any(AbortSignal)));
    expect(modelUrl).toHaveBeenCalledWith(character.avatars.l2d.model_path, "states/happy.json");
    fireEvent.change(screen.getByRole("textbox", { name: "Sprite tag" }), { target: { value: "smile" } });
    fireEvent.click(screen.getByRole("button", { name: "Save state" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(character));
    expect(saveModelState).toHaveBeenCalledWith({
      name: character.name,
      avatar_type: "l2d",
      model_path: character.avatars.l2d.model_path,
      sprite_index: 0,
      path: character.avatars.l2d.sprites[0].path,
      state: savedState,
      tags: "smile",
    });
  });

  it("shows failed state requests instead of allowing an invalid state to be saved", async () => {
    character.avatars.l2d = {
      model_path: "/models/haru.model3.json",
      sprites: [{ path: "/models/broken.json" }],
      emotion_tags: "",
    };
    fetchState.mockResolvedValue({ ok: false, status: 403 });
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Save state" })).toBeEnabled());
    fireEvent.click(screen.getByRole("combobox", { name: "Model state" }));
    fireEvent.click(screen.getByRole("option", { name: "1: broken.json" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("403"));
    expect(screen.getByRole("button", { name: "Save state" })).toBeDisabled();
  });

  it("uses the selected UI language for the model editor", () => {
    view(character, "zh_CN");
    expect(screen.getByRole("combobox", { name: "形象类型" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导入模型" })).toHaveClass("button");
    expect(screen.getByRole("textbox", { name: "本地模型入口" })).toHaveClass("input");
  });
});
