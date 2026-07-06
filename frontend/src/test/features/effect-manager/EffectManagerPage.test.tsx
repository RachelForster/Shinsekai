import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EffectManagerPage } from "../../../features/effect-manager/EffectManagerPage";
import type { Effect } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const pickerState = vi.hoisted(() => ({ paths: [] as string[] }));
const mockListEffects = vi.fn();
const mockSaveEffect = vi.fn();
const mockDeleteEffect = vi.fn();
const mockDeleteEffectAudio = vi.fn();
const mockDeleteAllEffectAudio = vi.fn();
const mockExportEffect = vi.fn();
const mockImportEffects = vi.fn();
const mockSaveEffectAudioTags = vi.fn();
const mockUploadEffectAudio = vi.fn();
const mockOpenExternal = vi.fn();

vi.mock("../../../shared/ui", async () => {
  const actual = await vi.importActual<typeof import("../../../shared/ui")>("../../../shared/ui");
  return {
    ...actual,
    PathPickerDialog({
      multiple,
      onClose,
      onSelect,
      onSelectMany,
      open,
      title,
    }: ComponentProps<typeof actual.PathPickerDialog>) {
      if (!open) {
        return null;
      }
      const paths = pickerState.paths.length ? pickerState.paths : ["D:/mock/selected.wav"];
      return (
        <div aria-label={title} role="dialog">
          <button
            onClick={() => {
              if (multiple && onSelectMany) {
                onSelectMany(paths);
              } else {
                onSelect(paths[0]);
              }
              onClose();
            }}
            type="button"
          >
            Choose mocked paths
          </button>
          <button onClick={onClose} type="button">
            Cancel picker
          </button>
        </div>
      );
    },
  };
});

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
  openExternal: (url: string) => mockOpenExternal(url),
}));

vi.mock("../../../entities/effect/repository", () => ({
  deleteAllEffectAudio: (name: string) => mockDeleteAllEffectAudio(name),
  deleteEffect: (name: string) => mockDeleteEffect(name),
  deleteEffectAudio: (name: string, index: number) => mockDeleteEffectAudio(name, index),
  effectsQueryKey: ["effects"],
  exportEffect: (name: string) => mockExportEffect(name),
  importEffects: (paths: string[]) => mockImportEffects(paths),
  listEffects: () => mockListEffects(),
  saveEffect: (effect: Effect, originalName?: string) => mockSaveEffect(effect, originalName),
  saveEffectAudioTags: (input: { audioTags: string; name: string }) => mockSaveEffectAudioTags(input),
  uploadEffectAudio: (input: { audioTags: string; name: string; paths: string[] }) => mockUploadEffectAudio(input),
}));

const effect: Effect = {
  audio_list: ["D:/effects/chime.wav", "D:/effects/boom.mp3"],
  audio_tags: "Effect 1: bright\nEffect 2: loud\n",
  color: "#123456",
  name: "Spark",
  prompt_text: "",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <EffectManagerPage />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("EffectManagerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickerState.paths = [];
    HTMLMediaElement.prototype.load = vi.fn();
    HTMLMediaElement.prototype.pause = vi.fn();
    HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    mockListEffects.mockResolvedValue([structuredClone(effect)]);
    mockSaveEffect.mockImplementation(async (input: Effect) => input);
    mockDeleteEffect.mockResolvedValue(undefined);
    mockDeleteEffectAudio.mockImplementation(async (name: string, index: number) => ({
      ...structuredClone(effect),
      audio_list: effect.audio_list.filter((_, itemIndex) => itemIndex !== index),
      audio_tags: "Effect 1: loud\n",
      name,
    }));
    mockDeleteAllEffectAudio.mockImplementation(async (name: string) => ({
      ...structuredClone(effect),
      audio_list: [],
      audio_tags: "",
      name,
    }));
    mockExportEffect.mockResolvedValue("D:/exports/Spark.ef");
    mockImportEffects.mockImplementation(async (paths: string[]) =>
      paths.map((path, index) => ({
        ...structuredClone(effect),
        name: index === 0 ? "Imported Spark" : `Imported ${index + 1}`,
        prompt_text: path,
      })),
    );
    mockSaveEffectAudioTags.mockImplementation(async ({ audioTags, name }) => ({
      ...structuredClone(effect),
      audio_tags: audioTags,
      name,
    }));
    mockUploadEffectAudio.mockImplementation(async ({ audioTags, name, paths }) => ({
      ...structuredClone(effect),
      audio_list: [...effect.audio_list, ...paths],
      audio_tags: `${audioTags}Effect 3: uploaded\n`,
      name,
    }));
  });

  it("saves edits, exports the selected effect, and opens community resources", async () => {
    renderPage();

    expect(await screen.findByDisplayValue("Spark")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Scheme name"), { target: { value: "Flash" } });
    fireEvent.change(screen.getAllByDisplayValue("#123456")[0], { target: { value: "#abcdef" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockSaveEffect).toHaveBeenCalledWith(
        expect.objectContaining({
          color: "#abcdef",
          name: "Flash",
        }),
        "Spark",
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(mockExportEffect).toHaveBeenCalledWith("Flash"));

    fireEvent.click(screen.getByRole("button", { name: "Download Effects" }));
    expect(mockOpenExternal).toHaveBeenCalledWith("https://shinsekai.end0rph1n.icu/resources");
  });

  it("saves the current draft as a new effect when New is clicked", async () => {
    renderPage();

    expect(await screen.findByDisplayValue("Spark")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Scheme name"), { target: { value: "Flash Copy" } });
    fireEvent.click(screen.getByRole("button", { name: "New" }));

    await waitFor(() =>
      expect(mockSaveEffect).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Flash Copy",
        }),
        undefined,
      ),
    );
  });

  it("blocks invalid unsaved effect actions before calling repositories", async () => {
    mockListEffects.mockResolvedValue([]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Validation failed")).toBeInTheDocument();
    expect(screen.getByText("Effect scheme name is required.")).toBeInTheDocument();
    expect(mockSaveEffect).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(screen.getAllByText("Export").length).toBeGreaterThan(1));
    expect(mockExportEffect).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Delete failed")).toBeInTheDocument();
    expect(screen.getByText("Failed to delete.")).toBeInTheDocument();
    expect(mockDeleteEffect).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Upload Audio" }));
    await waitFor(() => expect(screen.getAllByText("Upload Audio").length).toBeGreaterThan(1));
    expect(mockUploadEffectAudio).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Save prompts" }));
    await waitFor(() => expect(screen.getAllByText("Save prompts").length).toBeGreaterThan(1));
    expect(mockSaveEffectAudioTags).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Clear all audio" }));
    await waitFor(() => expect(screen.getAllByText("Clear all audio").length).toBeGreaterThan(1));
    expect(mockDeleteAllEffectAudio).not.toHaveBeenCalled();
  });

  it("auto-saves a new effect before uploading audio", async () => {
    mockListEffects.mockResolvedValue([]);
    mockSaveEffect.mockImplementation(async (input: Effect) => input);
    renderPage();

    fireEvent.change(screen.getByLabelText("Scheme name"), { target: { value: "Pulse" } });
    pickerState.paths = ["D:/effects/pulse.wav"];
    fireEvent.click(screen.getByRole("button", { name: "Upload Audio" }));

    await waitFor(() =>
      expect(mockSaveEffect).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Pulse",
        }),
        undefined,
      ),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "Upload Audio" })).getByText("Choose mocked paths"),
    );

    await waitFor(() =>
      expect(mockUploadEffectAudio).toHaveBeenCalledWith({
        audioTags: "",
        name: "Pulse",
        paths: ["D:/effects/pulse.wav"],
      }),
    );
  });

  it("imports packages and uploads audio through the path picker", async () => {
    renderPage();

    expect(await screen.findByDisplayValue("Spark")).toBeInTheDocument();
    pickerState.paths = ["D:/packs/spark.ef", "D:/packs/extra.ef"];
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Import" })).getByText("Choose mocked paths"));

    await waitFor(() => expect(mockImportEffects).toHaveBeenCalledWith(["D:/packs/spark.ef", "D:/packs/extra.ef"]));

    pickerState.paths = ["D:/effects/new-hit.wav"];
    fireEvent.click(screen.getByRole("button", { name: "Upload Audio" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Upload Audio" })).getByText("Choose mocked paths"));

    await waitFor(() =>
      expect(mockUploadEffectAudio).toHaveBeenCalledWith({
        audioTags: "Effect 1: bright\nEffect 2: loud\n",
        name: "Imported 2",
        paths: ["D:/effects/new-hit.wav"],
      }),
    );
    expect(await screen.findByText("new-hit.wav")).toBeInTheDocument();
  });

  it("saves audio prompts and confirms selected and bulk audio deletion", async () => {
    renderPage();

    expect(await screen.findByDisplayValue("bright")).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("bright"), { target: { value: "sharp" } });
    fireEvent.click(screen.getByRole("button", { name: "Save prompts" }));

    await waitFor(() =>
      expect(mockSaveEffectAudioTags).toHaveBeenCalledWith({
        audioTags: "特效 1：sharp\n特效 2：loud\n",
        name: "Spark",
      }),
    );

    fireEvent.click(screen.getByLabelText("Select audio #1"));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected audio" }));
    let dialog = screen.getByRole("dialog", { name: "Delete selected audio" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockDeleteEffectAudio).toHaveBeenCalledWith("Spark", 0));
    expect(screen.queryByText("chime.wav")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear all audio" }));
    dialog = screen.getByRole("dialog", { name: "Clear all audio" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockDeleteAllEffectAudio).toHaveBeenCalledWith("Spark"));
    expect(await screen.findByText(/No audio files yet/)).toBeInTheDocument();
  });

  it("surfaces failures from effect operations", async () => {
    mockSaveEffect.mockRejectedValueOnce(new Error("save boom"));
    mockExportEffect.mockRejectedValueOnce(new Error("export boom"));
    mockImportEffects.mockRejectedValueOnce(new Error("import boom"));
    mockUploadEffectAudio.mockRejectedValueOnce(new Error("upload boom"));
    mockSaveEffectAudioTags.mockRejectedValueOnce(new Error("tags boom"));
    mockDeleteAllEffectAudio.mockRejectedValueOnce(new Error("clear boom"));
    mockDeleteEffect.mockRejectedValueOnce(new Error("delete boom"));
    renderPage();

    expect(await screen.findByDisplayValue("Spark")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("save boom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(await screen.findByText("export boom")).toBeInTheDocument();

    pickerState.paths = ["D:/packs/broken.ef"];
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Import" })).getByText("Choose mocked paths"));
    expect(await screen.findByText("import boom")).toBeInTheDocument();

    pickerState.paths = ["D:/effects/broken.wav"];
    fireEvent.click(screen.getByRole("button", { name: "Upload Audio" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Upload Audio" })).getByText("Choose mocked paths"));
    expect(await screen.findByText("upload boom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save prompts" }));
    expect(await screen.findByText("tags boom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear all audio" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Clear all audio" })).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByText("clear boom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Delete effect scheme" })).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByText("delete boom")).toBeInTheDocument();
  });
});
