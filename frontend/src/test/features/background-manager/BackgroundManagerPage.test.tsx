import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BackgroundManagerPage } from "../../../features/background-manager/BackgroundManagerPage";
import type { Background } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const pickerState = vi.hoisted(() => ({ paths: [] as string[] }));
const mockListBackgrounds = vi.fn();
const mockSaveBackground = vi.fn();
const mockDeleteAllBackgroundBgm = vi.fn();
const mockDeleteAllBackgroundImages = vi.fn();
const mockDeleteBackground = vi.fn();
const mockDeleteBackgroundBgm = vi.fn();
const mockDeleteBackgroundImage = vi.fn();
const mockExportBackground = vi.fn();
const mockImportBackgrounds = vi.fn();
const mockOpenExternal = vi.fn();
const mockSaveBackgroundImageTags = vi.fn();
const mockTranslateBackgroundFields = vi.fn();
const mockUploadBackgroundBgm = vi.fn();
const mockUploadBackgroundImages = vi.fn();

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
      const paths = pickerState.paths.length ? pickerState.paths : ["D:/mock/selected.png"];
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
  fileThumbnailBatch: vi.fn().mockResolvedValue({}),
  fileThumbnailUrl: (path: string) => `thumb://${path}`,
  fileUrl: (path: string) => `asset://${path}`,
  openExternal: (url: string) => mockOpenExternal(url),
}));

vi.mock("../../../entities/background/repository", () => ({
  backgroundsQueryKey: ["backgrounds"],
  deleteAllBackgroundBgm: (name: string) => mockDeleteAllBackgroundBgm(name),
  deleteAllBackgroundImages: (name: string) => mockDeleteAllBackgroundImages(name),
  deleteBackground: (name: string) => mockDeleteBackground(name),
  deleteBackgroundBgm: (name: string, index: number) => mockDeleteBackgroundBgm(name, index),
  deleteBackgroundImage: (name: string, index: number) => mockDeleteBackgroundImage(name, index),
  exportBackground: (name: string) => mockExportBackground(name),
  importBackgrounds: (paths: string[]) => mockImportBackgrounds(paths),
  listBackgrounds: () => mockListBackgrounds(),
  saveBackground: (background: Background, originalName?: string) => mockSaveBackground(background, originalName),
  saveBackgroundBgmTags: vi.fn(),
  saveBackgroundImageTags: (input: { bgTags: string; name: string }) => mockSaveBackgroundImageTags(input),
  translateBackgroundFields: (input: unknown) => mockTranslateBackgroundFields(input),
  uploadBackgroundBgm: (input: { bgmTags: string; name: string; paths: string[] }) => mockUploadBackgroundBgm(input),
  uploadBackgroundImages: (input: { bgTags: string; name: string; paths: string[] }) =>
    mockUploadBackgroundImages(input),
}));

const background: Background = {
  bg_tags: "Scene 1: classroom\n",
  bgm_list: [],
  bgm_tags: "",
  name: "School",
  sprite_prefix: "school",
  sprites: [{ path: "D:/backgrounds/school/classroom.png" }],
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <BackgroundManagerPage />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("BackgroundManagerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickerState.paths = [];
    HTMLMediaElement.prototype.load = vi.fn();
    HTMLMediaElement.prototype.pause = vi.fn();
    HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    mockListBackgrounds.mockResolvedValue([structuredClone(background)]);
    mockSaveBackground.mockImplementation(async (input: Background) => input);
    mockDeleteBackground.mockResolvedValue(undefined);
    mockDeleteBackgroundImage.mockImplementation(async (name: string, index: number) => ({
      ...structuredClone(background),
      name,
      sprites: [{ path: index === 0 ? "D:/backgrounds/school/hall.png" : "D:/backgrounds/school/classroom.png" }],
    }));
    mockDeleteAllBackgroundImages.mockImplementation(async (name: string) => ({
      ...structuredClone(background),
      bg_tags: "",
      name,
      sprites: [],
    }));
    mockDeleteBackgroundBgm.mockImplementation(async (name: string, index: number) => ({
      ...structuredClone(background),
      bgm_list: ["D:/backgrounds/school/theme.mp3", "D:/backgrounds/school/rain.mp3"].filter(
        (_, itemIndex) => itemIndex !== index,
      ),
      bgm_tags: "",
      name,
    }));
    mockDeleteAllBackgroundBgm.mockImplementation(async (name: string) => ({
      ...structuredClone(background),
      bgm_list: [],
      bgm_tags: "",
      name,
    }));
    mockExportBackground.mockResolvedValue("D:/exports/School.bg");
    mockImportBackgrounds.mockImplementation(async (paths: string[]) =>
      paths.map((path, index) => ({
        ...structuredClone(background),
        name: index === 0 ? "Imported School" : `Imported ${index + 1}`,
        sprite_prefix: path,
      })),
    );
    mockOpenExternal.mockResolvedValue(undefined);
    mockSaveBackgroundImageTags.mockImplementation(async ({ bgTags, name }) => ({
      ...structuredClone(background),
      bg_tags: bgTags,
      name,
    }));
    mockTranslateBackgroundFields.mockResolvedValue({
      bgTags: "场景 1: 教室\n",
      bgmRowTags: ["安静"],
      bgmTags: "",
      name: "学校",
    });
    mockUploadBackgroundImages.mockImplementation(async ({ bgTags, name, paths }) => ({
      ...structuredClone(background),
      bg_tags: `${bgTags}Scene 2: uploaded\n`,
      name,
      sprites: [...background.sprites, ...paths.map((path) => ({ path }))],
    }));
    mockUploadBackgroundBgm.mockImplementation(async ({ bgmTags, name, paths }) => ({
      ...structuredClone(background),
      bgm_list: [...background.bgm_list, ...paths],
      bgm_tags: `${bgmTags}Music 1: uploaded\n`,
      name,
    }));
  });

  it("keeps a newly saved background selected", async () => {
    mockListBackgrounds.mockResolvedValue([]);
    renderPage();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "City" } });
    fireEvent.change(screen.getByLabelText("Resource directory"), { target: { value: "city" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockSaveBackground).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "City",
          sprite_prefix: "city",
        }),
        undefined,
      ),
    );
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveTextContent("City"));
  });

  it("shows empty and query error states for the background list", async () => {
    mockListBackgrounds.mockResolvedValueOnce([]);
    const emptyRender = renderPage();

    expect(await screen.findByText("Create a background group before using it in templates.")).toBeInTheDocument();
    expect(screen.getAllByText("No backgrounds").length).toBeGreaterThan(0);
    expect(screen.getByText("No background images")).toBeInTheDocument();
    expect(screen.getByText("No BGM entries")).toBeInTheDocument();

    emptyRender.unmount();
    mockListBackgrounds
      .mockRejectedValueOnce(new Error("load failed"))
      .mockResolvedValueOnce([structuredClone(background)]);
    renderPage();

    expect(await screen.findByText("Operation failed")).toBeInTheDocument();
    expect(screen.getByText("load failed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(mockListBackgrounds).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("School"));
  });

  it("blocks invalid unsaved background actions before calling repositories", async () => {
    mockListBackgrounds.mockResolvedValue([]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Validation failed")).toBeInTheDocument();
    expect(screen.getByText("Background name is required.")).toBeInTheDocument();
    expect(mockSaveBackground).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(screen.getAllByText("Export").length).toBeGreaterThan(1));
    expect(mockExportBackground).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "AI translate" }));
    await waitFor(() => expect(screen.getAllByText("Validation failed").length).toBeGreaterThan(1));
    expect(mockTranslateBackgroundFields).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Delete failed")).toBeInTheDocument();
    expect(screen.getByText("The background group was not deleted.")).toBeInTheDocument();
    expect(mockDeleteBackground).not.toHaveBeenCalled();
  });

  it("saves background info when batch image tags are confirmed", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("School"));
    fireEvent.click(screen.getByRole("button", { name: "Batch image tags" }));

    const dialog = screen.getByRole("dialog", { name: "Batch image tags" });
    fireEvent.change(within(dialog).getByLabelText("Image tags"), {
      target: { value: "Scene 1: night classroom\n" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(mockSaveBackground).toHaveBeenCalledWith(
        expect.objectContaining({
          bg_tags: "Scene 1: night classroom\n",
          name: "School",
          sprite_prefix: "school",
        }),
        "School",
      ),
    );
  });

  it("saves background info when batch BGM tags are confirmed", async () => {
    mockListBackgrounds.mockResolvedValue([
      {
        ...structuredClone(background),
        bgm_list: ["D:/backgrounds/school/theme.mp3"],
        bgm_tags: "Music 1: calm\n",
      },
    ]);
    renderPage();

    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("School"));
    fireEvent.click(screen.getByRole("button", { name: "Batch BGM tags" }));

    const dialog = screen.getByRole("dialog", { name: "Batch BGM tags" });
    fireEvent.change(within(dialog).getByLabelText("BGM tags"), {
      target: { value: "Music 1: tense\n" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(mockSaveBackground).toHaveBeenCalledWith(
        expect.objectContaining({
          bgm_tags: "Music 1: tense\n",
          name: "School",
          sprite_prefix: "school",
        }),
        "School",
      ),
    );
  });

  it("imports packages, uploads resources, exports, and opens background resource links", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("School"));
    fireEvent.click(screen.getByRole("button", { name: "Community backgrounds" }));
    fireEvent.click(screen.getByRole("button", { name: "Upload contribution" }));
    expect(mockOpenExternal).toHaveBeenCalledTimes(2);
    expect(mockOpenExternal).toHaveBeenCalledWith("https://shinsekai.end0rph1n.icu/resources");

    pickerState.paths = ["D:/packs/school.bg", "D:/packs/extra.bg"];
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Import" })).getByText("Choose mocked paths"));
    await waitFor(() => expect(mockImportBackgrounds).toHaveBeenCalledWith(pickerState.paths));
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("Imported 2"));

    pickerState.paths = ["D:/backgrounds/school/hall.png"];
    fireEvent.click(screen.getByRole("button", { name: "Upload images" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Select image files" })).getByText("Choose mocked paths"),
    );
    await waitFor(() =>
      expect(mockUploadBackgroundImages).toHaveBeenCalledWith({
        bgTags: "Scene 1: classroom\n",
        name: "Imported 2",
        paths: ["D:/backgrounds/school/hall.png"],
      }),
    );

    pickerState.paths = ["D:/backgrounds/school/theme.mp3"];
    fireEvent.click(screen.getByRole("button", { name: "Upload BGM" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Select BGM files" })).getByText("Choose mocked paths"));
    await waitFor(() =>
      expect(mockUploadBackgroundBgm).toHaveBeenCalledWith({
        bgmTags: "",
        name: "Imported 2",
        paths: ["D:/backgrounds/school/theme.mp3"],
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(mockExportBackground).toHaveBeenCalledWith("Imported 2"));
  });

  it("translates fields and saves the edited image tag", async () => {
    mockListBackgrounds.mockResolvedValue([
      {
        ...structuredClone(background),
        bgm_list: ["D:/backgrounds/school/theme.mp3"],
        bgm_tags: "Music 1: calm\n",
      },
    ]);
    renderPage();

    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("School"));
    fireEvent.click(screen.getByRole("button", { name: "AI translate" }));

    await waitFor(() =>
      expect(mockTranslateBackgroundFields).toHaveBeenCalledWith({
        bgTags: "Scene 1: classroom\n",
        bgmRowTags: ["calm"],
        bgmTags: "Music 1: calm\n",
        name: "School",
      }),
    );
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("学校"));

    fireEvent.change(screen.getAllByLabelText("Tag")[0], { target: { value: "translated classroom" } });
    fireEvent.click(screen.getByRole("button", { name: "Save image description" }));
    await waitFor(() =>
      expect(mockSaveBackgroundImageTags).toHaveBeenCalledWith({
        bgTags: "场景 1：translated classroom\n",
        name: "School",
      }),
    );
  });

  it("keeps the draft unchanged when AI translation returns an error", async () => {
    mockTranslateBackgroundFields.mockResolvedValueOnce({ error: "No translation available" });
    renderPage();

    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("School"));
    fireEvent.click(screen.getByRole("button", { name: "AI translate" }));

    await waitFor(() => expect(mockTranslateBackgroundFields).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("No translation available")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("School");
  });

  it("confirms image, bgm, and background deletion actions", async () => {
    mockListBackgrounds.mockResolvedValue([
      {
        ...structuredClone(background),
        bgm_list: ["D:/backgrounds/school/theme.mp3", "D:/backgrounds/school/rain.mp3"],
        bgm_tags: "Music 1: calm\nMusic 2: rainy\n",
        sprites: [{ path: "D:/backgrounds/school/classroom.png" }, { path: "D:/backgrounds/school/hall.png" }],
      },
    ]);
    renderPage();

    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("School"));

    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    let dialog = screen.getByRole("dialog", { name: "Remove" });
    expect(within(dialog).getByText(/Delete background image #1/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(mockDeleteBackgroundImage).toHaveBeenCalledWith("School", 0));

    fireEvent.click(screen.getByRole("button", { name: "Delete all images" }));
    dialog = screen.getByRole("dialog", { name: "Delete all images" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDeleteAllBackgroundImages).toHaveBeenCalledWith("School"));

    fireEvent.click(screen.getByLabelText("Select 1"));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected BGM" }));
    dialog = screen.getByRole("dialog", { name: "Delete selected BGM" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDeleteBackgroundBgm).toHaveBeenCalledWith("School", 0));

    fireEvent.click(screen.getByRole("button", { name: "Delete all BGM" }));
    dialog = screen.getByRole("dialog", { name: "Delete all BGM" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDeleteAllBackgroundBgm).toHaveBeenCalledWith("School"));

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    dialog = screen.getByRole("dialog", { name: "Delete background" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDeleteBackground).toHaveBeenCalledWith("School"));
  });
});
