import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BackgroundManagerPage } from "../../../features/background-manager/BackgroundManagerPage";
import type { Background } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mockListBackgrounds = vi.fn();
const mockSaveBackground = vi.fn();

vi.mock("../../../entities/files/repository", () => ({
  fileThumbnailBatch: vi.fn().mockResolvedValue({}),
  fileThumbnailUrl: (path: string) => `thumb://${path}`,
  fileUrl: (path: string) => `asset://${path}`,
  openExternal: vi.fn(),
}));

vi.mock("../../../entities/background/repository", () => ({
  backgroundsQueryKey: ["backgrounds"],
  deleteAllBackgroundBgm: vi.fn(),
  deleteAllBackgroundImages: vi.fn(),
  deleteBackground: vi.fn(),
  deleteBackgroundBgm: vi.fn(),
  deleteBackgroundImage: vi.fn(),
  exportBackground: vi.fn(),
  importBackgrounds: vi.fn(),
  listBackgrounds: () => mockListBackgrounds(),
  saveBackground: (background: Background, originalName?: string) => mockSaveBackground(background, originalName),
  saveBackgroundBgmTags: vi.fn(),
  saveBackgroundImageTags: vi.fn(),
  translateBackgroundFields: vi.fn(),
  uploadBackgroundBgm: vi.fn(),
  uploadBackgroundImages: vi.fn(),
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
    HTMLMediaElement.prototype.load = vi.fn();
    HTMLMediaElement.prototype.pause = vi.fn();
    HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    mockListBackgrounds.mockResolvedValue([structuredClone(background)]);
    mockSaveBackground.mockImplementation(async (input: Background) => input);
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

  it("saves background info when batch image tags are confirmed", async () => {
    renderPage();

    await screen.findByDisplayValue("School");
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

    await screen.findByDisplayValue("School");
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
});
