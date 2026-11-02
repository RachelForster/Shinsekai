import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { KnowledgeManagerPage } from "../../../features/knowledge-manager/KnowledgeManagerPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { Mem0Status } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({
  preview: vi.fn(),
  execute: vi.fn(),
  status: vi.fn(),
  characters: vi.fn(),
  bind: vi.fn(),
  instances: vi.fn(),
  entries: vi.fn(),
}));
vi.mock("../../../entities/character/repository", () => ({
  listCharacters: mocks.characters,
  charactersQueryKey: ["characters"],
}));
vi.mock("../../../entities/knowledge/repository", async (original) => ({
  ...(await original<object>()),
  previewKnowledgeImport: mocks.preview,
  importKnowledge: mocks.execute,
  getKnowledgeStatus: mocks.status,
  addKnowledgeBinding: mocks.bind,
  listKnowledgeInstances: mocks.instances,
  listKnowledgeEntries: mocks.entries,
  listKnowledgeBindingNames: async () => ({ knowledge_id: "alpha", characterNames: [] }),
}));

beforeEach(() => {
  vi.resetAllMocks();
  mocks.status.mockResolvedValue({ status: "ready" });
  mocks.preview.mockResolvedValue({
    fileCount: 1,
    chunkCount: 1,
    dialogueCharacters: 20,
    dialogueLineCount: 1,
    sourceTokens: 5,
    estimatedInputTokens: 8,
    estimatedOutputTokens: 2,
    estimatedTotalTokens: 10,
    files: [{ name: "knowledge.txt", kind: "txt", chunkCount: 1, sourceTokens: 5 }],
    warnings: [],
  });
  mocks.execute.mockResolvedValue({ knowledge_id: "alpha", savedCount: 1 });
  mocks.characters.mockResolvedValue([]);
  mocks.instances.mockResolvedValue({
    count: 1,
    page: 1,
    pageSize: 20,
    knowledge: [{ knowledge_id: "alpha", entryCount: 1, characterCount: 0 }],
  });
  mocks.entries.mockResolvedValue({
    knowledge_id: "alpha",
    count: 1,
    memories: [{ id: "entry", memory: "Independent knowledge knowledge" }],
  });
});

afterEach(() => {
  vi.useRealTimers();
});

function renderPage(embedded = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <ToastProvider>
          <KnowledgeManagerPage embedded={embedded} />
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

it.each([false, true])("places refresh after file import in embedded=%s mode", async (embedded) => {
  renderPage(embedded);
  const importButton = screen.getByRole("button", { name: "Import from files" });
  expect(screen.queryByRole("button", { name: "New" })).not.toBeInTheDocument();
  expect(importButton).toHaveClass("button--ghost");
  const refreshButton = screen.getByRole("button", { name: "Refresh" });
  expect(importButton.parentElement).toBe(refreshButton.parentElement);
  expect(importButton.compareDocumentPosition(refreshButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(refreshButton);
  await waitFor(() => expect(mocks.instances).toHaveBeenCalledWith({ query: "", page: 1, refresh: true }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it.each([false, true])("shows model progress on first refresh with modelCached=%s", async (modelCached) => {
  vi.useFakeTimers();
  let resolveStatus!: (status: Mem0Status) => void;
  mocks.status
    .mockImplementationOnce(
      () =>
        new Promise<Mem0Status>((resolve) => {
          resolveStatus = resolve;
        }),
    )
    .mockResolvedValue({ status: "ready" });
  renderPage(true);
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  const dialog = screen.getByRole("dialog", { name: "Material management" });
  expect(within(dialog).getByText("Loading embedding model…")).toBeVisible();
  expect(within(dialog).getByRole("progressbar", { name: "Loading embedding model…" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  expect(mocks.instances).not.toHaveBeenCalled();
  await act(async () => {
    resolveStatus({
      status: "loading",
      modelCached,
      task: {
        id: "knowledge-model",
        kind: "knowledge_init",
        title: "Material management",
        status: "running",
        phase: "initialize",
        progress: 0.5,
        message: "Initializing knowledge.",
        logs: [],
        createdAt: 0,
        updatedAt: 0,
      },
    });
  });
  expect(
    within(dialog).getByText(modelCached ? "Loading embedding model…" : "Downloading embedding model…"),
  ).toBeVisible();
  expect(within(dialog).getByRole("status")).toHaveTextContent("50%");
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  expect(mocks.instances).not.toHaveBeenCalled();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mocks.instances).toHaveBeenCalledWith({ query: "", page: 1, refresh: true });
  expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
});

it("reports initialization failure and allows an explicit refresh retry", async () => {
  mocks.status
    .mockResolvedValueOnce({ status: "error", message: "Model initialization failed" })
    .mockResolvedValue({ status: "ready" });
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByText("Model initialization failed")).toBeVisible();
  await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled());
  expect(mocks.instances).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(mocks.instances).toHaveBeenCalledWith({ query: "", page: 1, refresh: true }));
  expect(mocks.status.mock.calls).toEqual([
    [{ startLoading: true, retry: true }],
    [{ startLoading: true, retry: true }],
  ]);
});

it("imports without any character and keeps the browsing query independent", async () => {
  renderPage();
  expect(screen.getByRole("heading", { name: "Material management" })).toBeVisible();
  const query = screen.getByRole("combobox");
  expect(query).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "Import from files" }));
  const picker = screen.getByRole("dialog");
  const next = within(picker).getByRole("button", { name: "Next: preview import" });
  expect(next).toBeDisabled();
  const file = new File(["knowledge knowledge"], "knowledge.txt", { type: "text/plain" });
  fireEvent.change(within(picker).getByLabelText("Select TXT files"), { target: { files: [file] } });
  expect(next).toBeDisabled();
  fireEvent.change(within(picker).getByRole("textbox", { name: "Material name" }), {
    target: { value: " alpha " },
  });
  expect(next).toBeEnabled();
  fireEvent.click(next);
  expect(await screen.findByText(/Import target:/)).toHaveTextContent("alpha");
  expect(mocks.preview).toHaveBeenCalledWith("alpha", [file]);
  fireEvent.change(query, { target: { value: "unrelated search" } });
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Import" }));
  await waitFor(() => expect(mocks.execute).toHaveBeenCalledWith("alpha", [file], expect.any(Object)));
  expect(query).toHaveValue("unrelated search");
  expect(mocks.status).toHaveBeenCalledWith({ startLoading: true, retry: false });
  expect(mocks.bind).not.toHaveBeenCalled();
});

it("embedded material management hides bindings initially and shows them once entries are ready", async () => {
  renderPage(true);
  expect(screen.getByRole("region", { name: "Material information" })).toBeVisible();
  expect(screen.queryByRole("region", { name: "Bound characters" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Available materials" }));
  fireEvent.click(await screen.findByRole("option", { name: /alpha/ }));
  expect(await screen.findByText("Independent knowledge knowledge")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Entry content" })).toBeEnabled();
  expect(await screen.findByRole("region", { name: "Bound characters" })).toBeVisible();
  await waitFor(() => expect(mocks.characters).toHaveBeenCalled());
});

it("embedded material management keeps bindings hidden until the selected material finishes loading", async () => {
  const entries = mocks.entries.getMockImplementation()!;
  let finishLoading!: (value: Awaited<ReturnType<typeof entries>>) => void;
  mocks.entries.mockReturnValue(
    new Promise((resolve) => {
      finishLoading = resolve;
    }),
  );
  renderPage(true);
  fireEvent.click(screen.getByRole("button", { name: "Available materials" }));
  fireEvent.click(await screen.findByRole("option", { name: /alpha/ }));
  await waitFor(() => expect(mocks.entries).toHaveBeenCalled());
  expect(screen.queryByRole("region", { name: "Bound characters" })).not.toBeInTheDocument();
  await act(async () => {
    finishLoading(await entries());
  });
  expect(await screen.findByText("Independent knowledge knowledge")).toBeVisible();
  expect(await screen.findByRole("region", { name: "Bound characters" })).toBeVisible();
});

it("allows knowledge management with an empty character list", async () => {
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "Available materials" }));
  fireEvent.click(await screen.findByRole("option", { name: /alpha/ }));
  expect(await screen.findByText("Independent knowledge knowledge")).toBeVisible();
  expect(
    await screen.findByText("Create a character to add a binding. Materials can still be managed independently."),
  ).toBeVisible();
  expect(await screen.findByText("Independent knowledge knowledge")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Entry content" })).toBeEnabled();
  expect(mocks.bind).not.toHaveBeenCalled();
});

it("allows importing into a new material ID after selecting an existing material", async () => {
  renderPage();
  const header = screen.getByRole("banner");
  expect(within(header).getByRole("navigation", { name: "Material views" })).toBeVisible();
  expect(screen.getByRole("region", { name: "Material information" })).toBeVisible();
  expect(screen.getByRole("region", { name: "Bound characters" })).toBeVisible();
  expect(within(header).getByRole("combobox")).toBeVisible();
  fireEvent.click(within(header).getByRole("button", { name: "Available materials" }));
  fireEvent.click(await within(header).findByRole("option", { name: /alpha/ }));
  fireEvent.click(within(header).getByRole("button", { name: "Import from files" }));
  expect(within(screen.getByRole("dialog")).getByRole("textbox", { name: "Material name" })).toHaveValue("alpha");
  const dialog = screen.getByRole("dialog", { name: "Import material" });
  const target = within(dialog).getByRole("textbox", { name: "Material name" });
  expect(target).toHaveValue("alpha");
  fireEvent.change(target, { target: { value: "new-knowledge" } });
  fireEvent.change(within(dialog).getByLabelText("Select TXT files"), {
    target: { files: [new File(["knowledge"], "new.txt", { type: "text/plain" })] },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Next: preview import" }));
  await waitFor(() => expect(mocks.preview).toHaveBeenCalledWith("new-knowledge", expect.any(Array)));
});
