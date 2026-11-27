import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NovelTheaterWizardPage } from "../../../features/novel-theater/NovelTheaterWizardPage";
import { I18nProvider } from "../../../shared/i18n";

const mocks = vi.hoisted(() => ({
  listNovelDocuments: vi.fn(),
  importNovelDocument: vi.fn(),
  getNovelDocument: vi.fn(),
  deleteNovelDocument: vi.fn(),
  extractNovelCast: vi.fn(),
  prepareNovelLaunchPayload: vi.fn(),
  listCharacters: vi.fn(),
  listBackgrounds: vi.fn(),
  launchChat: vi.fn(),
}));

vi.mock("../../../entities/novel/repository", () => ({
  novelDocumentsQueryKey: ["novel", "documents"],
  listNovelDocuments: mocks.listNovelDocuments,
  importNovelDocument: mocks.importNovelDocument,
  getNovelDocument: mocks.getNovelDocument,
  deleteNovelDocument: mocks.deleteNovelDocument,
  extractNovelCast: mocks.extractNovelCast,
  prepareNovelLaunchPayload: mocks.prepareNovelLaunchPayload,
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: mocks.listCharacters,
}));

vi.mock("../../../entities/background/repository", () => ({
  backgroundsQueryKey: ["backgrounds"],
  listBackgrounds: mocks.listBackgrounds,
}));

vi.mock("../../../entities/chat/repository", () => ({
  chatQueryKey: ["chat"],
  conversationsQueryKey: ["chat", "conversations"],
  launchChat: mocks.launchChat,
}));

function renderWizard(props: { onLaunchStarted?: () => void; onLaunched?: () => void } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <NovelTheaterWizardPage {...props} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const sampleDoc = {
  manifest: {
    docId: "doc-abc",
    title: "Mist Harbor",
    sourceFormat: "txt",
    sourceFilename: "mist.txt",
    totalChars: 2400,
    totalChunks: 4,
    totalChapters: 2,
    createdAtMs: 1000,
    pageCount: null,
    chunkConfig: { maxChars: 1400 },
  },
  chapters: [
    { index: 0, title: "Chapter 1 Dawn", startChunkIndex: 0, chunkCount: 2, pageStart: null, pageEnd: null },
    { index: 1, title: "Chapter 2 Noon", startChunkIndex: 2, chunkCount: 2, pageStart: null, pageEnd: null },
  ],
  sampleChunks: [],
};

describe("NovelTheaterWizardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listNovelDocuments.mockResolvedValue([sampleDoc]);
    mocks.getNovelDocument.mockResolvedValue(sampleDoc);
    mocks.listCharacters.mockResolvedValue([{ name: "Alice", sprites: [] }]);
    mocks.listBackgrounds.mockResolvedValue([{ name: "Harbor" }]);
    mocks.launchChat.mockResolvedValue({ sessionId: "sess-1" });
    mocks.prepareNovelLaunchPayload.mockResolvedValue({
      behaviorId: "novel_theater",
      novelDocId: "doc-abc",
      characters: [],
      backgroundName: "",
      historyPath: "h/novel-1.json",
      templateId: "",
    });
  });

  it("imports TXT documents, extracts cast, and binds characters", async () => {
    mocks.listNovelDocuments.mockResolvedValueOnce([]).mockResolvedValue([sampleDoc]);
    mocks.importNovelDocument.mockResolvedValue(sampleDoc);
    mocks.extractNovelCast.mockResolvedValue({
      docId: "doc-abc",
      characters: [
        {
          name: "Alice",
          aliases: ["Miss A"],
          role: "protagonist",
          description: "Lead traveler",
          isFirstPerson: false,
          suggestedCharacter: "Alice",
        },
      ],
      availableCharacters: [{ name: "Alice", brief: "" }],
    });

    renderWizard();
    expect(await screen.findByText(/No imported novels yet/i)).toBeVisible();

    const fileInput = screen.getByLabelText("Upload TXT / PDF novel");
    const file = new File(["Chapter 1 Dawn\nHello"], "mist.txt", { type: "text/plain" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(mocks.importNovelDocument).toHaveBeenCalledWith(file));
    expect(await screen.findByText("Chapter 1 Dawn")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(await screen.findByRole("button", { name: "AI extract cast" }));

    await waitFor(() => expect(mocks.extractNovelCast).toHaveBeenCalledWith("doc-abc"));
    expect(await screen.findByLabelText("Novel character 1")).toHaveValue("Alice");
    expect(screen.getByRole("combobox", { name: "Local character 1" })).toHaveTextContent("Alice");

    // Naming mode defaults to "actor", offers a ? help tooltip, and can switch to "story"
    const actorRadio = screen.getByRole("radio", { name: "Use actor names" });
    const storyRadio = screen.getByRole("radio", { name: "Keep novel names" });
    expect(actorRadio).toBeChecked();
    expect(storyRadio).not.toBeChecked();

    const helpButton = screen.getByRole("button", { name: "About character naming modes" });
    const tooltipId = helpButton.getAttribute("aria-describedby") ?? "";
    expect(tooltipId).toBeTruthy();
    const tooltip = document.getElementById(tooltipId);
    expect(tooltip).toHaveAttribute("role", "tooltip");
    expect(tooltip).toHaveTextContent(/Use actor names:/i);
    fireEvent.click(helpButton);
    expect(helpButton).toHaveAttribute("aria-expanded", "true");

    // Duplicate local target warning appears when two rows share a local character in actor mode
    fireEvent.click(screen.getByRole("button", { name: "Add binding" }));
    fireEvent.click(screen.getByRole("combobox", { name: "Local character 2" }));
    fireEvent.click(await screen.findByRole("option", { name: "Alice" }));
    expect(screen.getByRole("note")).toHaveTextContent(/share the same local character/i);

    fireEvent.click(storyRadio);
    expect(storyRadio).toBeChecked();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Start Novel Theater" }));
    await waitFor(() =>
      expect(mocks.prepareNovelLaunchPayload).toHaveBeenCalledWith(
        expect.objectContaining({
          docId: "doc-abc",
          nameMode: "story",
        }),
      ),
    );
  });

  it("supports one-click skip-casting pure dialogue launch", async () => {
    const onLaunched = vi.fn();
    renderWizard({ onLaunched });

    expect(await screen.findByText("Mist Harbor")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    fireEvent.click(await screen.findByRole("button", { name: "Skip casting & start now" }));

    await waitFor(() =>
      expect(mocks.prepareNovelLaunchPayload).toHaveBeenCalledWith(
        expect.objectContaining({
          docId: "doc-abc",
          casting: [],
        }),
      ),
    );
    await waitFor(() => expect(mocks.launchChat).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
  });
});
