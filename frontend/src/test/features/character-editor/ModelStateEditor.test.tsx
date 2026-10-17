import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Character } from "../../../entities/config/types";
import type { AvatarSession } from "../../../modules/character-visual/contracts";
import l2dFormat from "../../../modules/character-visual/adapters/l2d/format";
import { clearRegisteredAvatarFormats, registerAvatarFormat } from "../../../modules/character-visual/registry";
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
const importModelStates = vi.fn();
const saveModelState = vi.fn();
const modelUrl = vi.fn((_model: string, path: string) => `http://localhost/api/avatar/file?path=${path}`);
const fetchState = vi.fn();

function view(draft = character, language: "en" | "zh_CN" = "en") {
  const onChange = vi.fn();
  const onSaved = vi.fn();
  function Harness() {
    const [current, setCurrent] = useState(draft);
    return (
      <ModelStateEditor
        character={current}
        onChange={(next) => {
          onChange(next);
          setCurrent(next);
        }}
        onSaved={(next) => {
          onSaved(next);
          setCurrent(next);
        }}
      />
    );
  }
  const rendered = render(
    <I18nProvider language={language}>
      <Harness />
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
  registerAvatarFormat({
    ...l2dFormat,
    load: async () => ({
      create: async () => {
        state = structuredClone(neutral);
        return session;
      },
      Editor: ({ onChange }) => (
        <button onClick={() => onChange({ ...neutral, parameters: { ParamAngleX: 12 } })}>Change angle</button>
      ),
    }),
  });
  window.__SHINSEKAI_IPC__ = {
    characters: { importModel, importModelStates, saveModelState },
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
  it("batch imports opaque presets through shared multiple selection and preserves preview state", async () => {
    clearRegisteredAvatarFormats();
    registerAvatarFormat({
      ...l2dFormat,
      stateExtensions: [".pose", ".motion"],
      load: async () => ({
        create: async () => session,
        Editor: () => null,
      }),
    });
    character.avatars.l2d.model_path = "C:/models/haru.model3.json";
    character.avatars.l2d.sprites = [
      { path: "C:/models/old.json", voice_path: "", voice_text: "", voice_type: "fallback" },
    ];
    const base = { parameters: { ParamAngleX: 12 }, expressions: [], motion: "" };
    fetchState.mockResolvedValue({ ok: true, json: async () => base });
    const imported = structuredClone(character);
    imported.avatars.l2d.sprites.push({ ...character.avatars.l2d.sprites[0], path: "C:/models/new.json" });
    importModelStates.mockResolvedValue(imported);
    pickPath.mockResolvedValue(["C:/motions/one.pose", "C:/motions/two.motion"]);
    const { onSaved } = view();
    await waitFor(() => expect(session.apply).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Pose / motion files (multiple selection)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Import presets in batch" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Import presets in batch" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(imported));
    expect(importModelStates).toHaveBeenCalledWith({
      name: character.name,
      avatar_type: "l2d",
      model_path: character.avatars.l2d.model_path,
      source_paths: ["C:/motions/one.pose", "C:/motions/two.motion"],
      state: base,
    });
    expect(pickPath).toHaveBeenCalledWith(expect.objectContaining({ multiple: true }));
  });

  it("replays an existing motion without recreating the loaded model", async () => {
    character.avatars.l2d.model_path = "C:/models/haru.model3.json";
    character.avatars.l2d.sprites = [
      { path: "C:/models/old.json", voice_path: "", voice_text: "", voice_type: "fallback" },
    ];
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Play preset" })).toBeEnabled());
    const before = vi.mocked(session.apply).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Play preset" }));
    await waitFor(() => expect(vi.mocked(session.apply).mock.calls.length).toBeGreaterThan(before));
    expect(session.apply).toHaveBeenLastCalledWith(neutral, "play", expect.any(AbortSignal));
    expect(session.dispose).not.toHaveBeenCalled();
  });
  it("selects, imports and edits an opaque format without any Live2D registration", async () => {
    clearRegisteredAvatarFormats();
    const load = vi.fn(async () => ({
      create: async () => {
        let value: unknown = { pose: [0] };
        return {
          capabilities: { mouth: false, blink: false, motion: false, sampling: "none" as const },
          controls: {},
          apply: async (next: unknown) => {
            value = next;
          },
          readState: () => value,
          resize: () => {},
          setMouthOpen: () => {},
          dispose: () => {},
        };
      },
      Editor: ({ onChange }: { onChange: (state: unknown) => void }) => (
        <button onClick={() => onChange({ pose: [1, 2, 3] })}>Change demo pose</button>
      ),
    }));
    registerAvatarFormat({
      id: "demo",
      label: "Demo",
      load,
      capabilities: { mouth: false, blink: false, motion: false, sampling: "none" },
    });
    const draft = { ...character, avatar_type: "static", avatars: {} };
    const imported = {
      ...draft,
      avatar_type: "demo",
      avatars: { demo: { model_path: "/models/test.demo", sprites: [], emotion_tags: "" } },
    };
    importModel.mockResolvedValue(imported);
    saveModelState.mockResolvedValue(imported);
    const { onChange } = view(draft);
    fireEvent.click(screen.getByRole("combobox", { name: "Avatar format" }));
    fireEvent.click(screen.getByRole("option", { name: "Demo" }));
    expect(onChange).toHaveBeenCalledWith({
      ...draft,
      avatar_type: "demo",
      avatars: { demo: { model_path: "", sprites: [], emotion_tags: "" } },
    });
    expect(load).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Model entry" }), { target: { value: "/source/test.demo" } });
    fireEvent.click(screen.getByRole("button", { name: "Import model" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "New state" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "New state" }));
    fireEvent.click(await screen.findByRole("button", { name: "Change demo pose" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save state" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Save state" }));
    await waitFor(() =>
      expect(saveModelState).toHaveBeenCalledWith(
        expect.objectContaining({
          avatar_type: "demo",
          model_path: "/models/test.demo",
          state: { pose: [1, 2, 3] },
          sprite_index: -1,
        }),
      ),
    );
    expect(load).toHaveBeenCalledOnce();
  });

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
      avatars: { ...draft.avatars, l2d: { model_path: "", sprites: [], emotion_tags: "" } },
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
    fireEvent.click(screen.getByRole("option", { name: "Image / video sprites" }));
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
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save state" })).not.toBeInTheDocument();
    expect(modelUrl).toHaveBeenCalledWith(character.avatars.l2d.model_path, "haru.model3.json");
    fireEvent.click(screen.getByRole("button", { name: "Edit state" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save state" })).toBeEnabled());
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
    fireEvent.click(screen.getByRole("button", { name: "Edit state" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("403"));
    expect(screen.getByRole("button", { name: "Save state" })).toBeDisabled();
  });

  it("uses the selected UI language for the model editor", () => {
    view(character, "zh_CN");
    expect(screen.getByRole("combobox", { name: "形象类型" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导入模型" })).toHaveClass("button");
    expect(screen.getByRole("textbox", { name: "本地模型入口" })).toHaveClass("input");
  });

  it("keeps the imported model format after the saved character refresh", async () => {
    character = { ...character, avatar_type: "static", avatars: {} };
    const imported = {
      ...character,
      avatar_type: "l2d",
      avatars: {
        l2d: {
          model_path: "/models/haru.model3.json",
          sprites: [],
          emotion_tags: "",
        },
      },
    };
    importModel.mockResolvedValue(imported);
    view();
    fireEvent.click(screen.getByRole("combobox", { name: "Avatar format" }));
    fireEvent.click(screen.getByRole("option", { name: "Live2D Cubism" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Model entry" }), {
      target: { value: "/source/haru.model3.json" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import model" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "New state" })).toBeEnabled());
    expect(screen.getByRole("combobox", { name: "Avatar format" })).toHaveTextContent("Live2D Cubism");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Model preview")).toBeInTheDocument();
  });

  it("browses saved states in the shared gallery without opening parameters", async () => {
    character.avatars.l2d = {
      model_path: "/models/haru.model3.json",
      sprites: [{ path: "/models/states/happy.json" }, { path: "/models/states/sad.json" }],
      emotion_tags: "Sprite 1: happy\nSprite 2: sad\n",
    };
    view();
    const second = screen.getByRole("button", { name: "2 sad Model state Live2D Cubism" });
    fireEvent.click(second);
    expect(second).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(modelUrl).toHaveBeenCalledWith("/models/haru.model3.json", "states/sad.json"));
    await waitFor(() => expect(session.apply).toHaveBeenCalledWith(neutral, "restore", expect.any(AbortSignal)));
    expect(screen.queryByRole("button", { name: "Change angle" })).not.toBeInTheDocument();
    expect(saveModelState).not.toHaveBeenCalled();
  });

  it("creates a neutral state only after New, saves it and selects the appended gallery item", async () => {
    character.avatars.l2d = {
      model_path: "/models/haru.model3.json",
      sprites: [{ path: "/models/states/happy.json" }],
      emotion_tags: "Sprite 1: happy\n",
    };
    fetchState.mockResolvedValue({ ok: true, json: async () => ({ ...neutral, parameters: { ParamAngleX: 30 } }) });
    const result = structuredClone(character);
    result.avatars.l2d.sprites.push({ path: "/models/states/new.json" });
    result.avatars.l2d.emotion_tags += "Sprite 2: smile\n";
    saveModelState.mockResolvedValue(result);
    const { onSaved } = view();
    expect(screen.queryByRole("button", { name: "Change angle" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New state" }));
    const dialog = screen.getByRole("dialog", { name: "New state" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Save state" })).toBeEnabled());
    expect(session.apply).toHaveBeenCalledWith(neutral, "edit", expect.any(AbortSignal));
    expect(dialog.querySelector(".model-state-dialog__parameters")).toContainElement(
      within(dialog).getByRole("button", { name: "Change angle" }),
    );
    expect(dialog.querySelector(".model-state-dialog__preview")).toBe(
      within(dialog).getByRole("img", { name: "Model preview" }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Change angle" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Save state" })).toBeEnabled());
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Sprite tag" }), { target: { value: "smile" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save state" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(result));
    expect(saveModelState).toHaveBeenCalledWith({
      name: character.name,
      avatar_type: "l2d",
      model_path: "/models/haru.model3.json",
      sprite_index: -1,
      path: "",
      state: { ...neutral, parameters: { ParamAngleX: 12 } },
      tags: "smile",
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 smile Model state Live2D Cubism" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("cancels a draft without saving and releases the edit instance", async () => {
    character.avatars.l2d.model_path = "/models/haru.model3.json";
    view();
    fireEvent.click(screen.getByRole("button", { name: "New state" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Change angle" })).toBeInTheDocument());
    const disposals = vi.mocked(session.dispose).mock.calls.length;
    const resizes = vi.mocked(session.resize).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(saveModelState).not.toHaveBeenCalled();
    expect(session.dispose).toHaveBeenCalledTimes(disposals + 1);
    await waitFor(() => expect(vi.mocked(session.resize).mock.calls.length).toBeGreaterThan(resizes));
  });

  it("keeps a failed save draft open and allows retrying without changing parameters", async () => {
    character.avatars.l2d.model_path = "/models/haru.model3.json";
    saveModelState.mockRejectedValueOnce(new Error("Save failed")).mockResolvedValue(character);
    const { onSaved } = view();
    fireEvent.click(screen.getByRole("button", { name: "New state" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save state" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Save state" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Save failed"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save state" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(character));
    expect(saveModelState).toHaveBeenCalledTimes(2);
  });
});
