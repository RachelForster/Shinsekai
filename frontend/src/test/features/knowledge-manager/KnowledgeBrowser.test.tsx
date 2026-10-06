import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeInstancePicker } from "../../../features/knowledge-manager/KnowledgeInstancePicker";
import { KnowledgeBrowser } from "../../../features/knowledge-manager/KnowledgeBrowser";
import { useKnowledgeController } from "../../../features/knowledge-manager/useKnowledgeController";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({
  instances: vi.fn(),
  entries: vi.fn(),
  search: vi.fn(),
  bind: vi.fn(),
  bindingNames: vi.fn(),
  batch: vi.fn(),
  add: vi.fn(),
  remove: vi.fn(),
  deleteKnowledge: vi.fn(),
  status: vi.fn(),
}));
vi.mock("../../../entities/character/repository", () => ({
  listCharacters: async () => [{ name: "A" }, { name: "B" }],
  charactersQueryKey: ["characters"],
}));
vi.mock("../../../entities/knowledge/repository", async (original) => ({
  ...(await original<object>()),
  listKnowledgeInstances: mocks.instances,
  listKnowledgeEntries: mocks.entries,
  searchKnowledgeEntries: mocks.search,
  addKnowledgeBinding: mocks.bind,
  listKnowledgeBindingNames: mocks.bindingNames,
  batchKnowledgeBindings: mocks.batch,
  addKnowledgeEntry: mocks.add,
  deleteKnowledgeEntry: mocks.remove,
  deleteKnowledge: mocks.deleteKnowledge,
  getKnowledgeStatus: mocks.status,
}));

function Harness() {
  const controller = useKnowledgeController();
  return (
    <>
      <KnowledgeInstancePicker controller={controller} />
      <KnowledgeBrowser controller={controller} />
    </>
  );
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <ToastProvider>
          <Harness />
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

async function chooseKnowledge(id = "alpha") {
  fireEvent.click(screen.getByRole("button", { name: "Available materials" }));
  fireEvent.click(await screen.findByRole("option", { name: new RegExp(id) }));
}

describe("knowledge browser", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.bindingNames.mockResolvedValue({ knowledge_id: "alpha", characterNames: [] });
    mocks.status.mockResolvedValue({ status: "ready" });
    mocks.instances.mockResolvedValue({
      count: 2,
      page: 1,
      pageSize: 20,
      knowledge: [
        { knowledge_id: "alpha", entryCount: 10, characterCount: 9 },
        { knowledge_id: "beta", entryCount: 0, characterCount: 0 },
      ],
    });
    mocks.entries.mockImplementation(async (knowledgeId) => ({
      knowledge_id: knowledgeId,
      memories:
        knowledgeId === "alpha"
          ? Array.from({ length: 9 }, (_, i) => ({
              id: String(i),
              memory: i === 0 ? "First page setting" : i === 8 ? "Second page setting" : `Setting ${i}`,
            }))
          : [],
      count: knowledgeId === "alpha" ? 9 : 0,
    }));
    mocks.search.mockResolvedValue({
      knowledge_id: "alpha",
      query: "fog",
      count: 1,
      memories: [{ id: "match", memory: "Fog result" }],
    });
  });

  it("searches IDs, selects a knowledge, and paginates entries without character pagination", async () => {
    setup();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "alp" } });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: /alpha/ }));
    expect(mocks.instances).toHaveBeenCalledWith({ query: "alp", page: 1 });
    expect(screen.getByRole("combobox")).toHaveValue("alp");
    expect(await screen.findByText("First page setting")).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByRole("region", { name: "Material information" })).getByRole("button", { name: "Next page" }),
    );
    expect(await screen.findByText("Second page setting")).toBeInTheDocument();
    expect(mocks.entries).toHaveBeenCalledTimes(1);
    expect(mocks.entries).toHaveBeenCalledWith("alpha");
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    expect(screen.queryByText("First page setting")).not.toBeInTheDocument();
    const bindings = within(screen.getByRole("region", { name: "Bound characters" }));
    expect(await bindings.findByRole("button", { name: "A" })).toBeVisible();
    expect(bindings.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
  });

  it("opens matching materials after typing and loads entries only after selection", async () => {
    mocks.instances.mockResolvedValue({
      count: 1,
      page: 1,
      pageSize: 20,
      knowledge: [{ knowledge_id: "alpha", entryCount: 9, characterCount: 0 }],
    });
    setup();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "  First page  " } });
    const option = await screen.findByRole("option", { name: /alpha/ });
    expect(mocks.instances).toHaveBeenCalledWith({ query: "First page", page: 1 });
    expect(mocks.entries).not.toHaveBeenCalled();
    expect(input).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(option);
    expect(await screen.findByText("First page setting")).toBeVisible();
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(mocks.entries).toHaveBeenCalledWith("alpha");
  });

  it("searches immediately with the search button and shows an empty result", async () => {
    mocks.instances.mockResolvedValue({ count: 0, page: 1, pageSize: 20, knowledge: [] });
    setup();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "missing" } });
    fireEvent.click(screen.getByRole("button", { name: "Search related materials" }));
    expect(await screen.findByText("No matching materials")).toBeVisible();
    expect(mocks.instances).toHaveBeenCalledWith({ query: "missing", page: 1 });
    expect(mocks.entries).not.toHaveBeenCalled();
  });

  it("disables binding actions while saving and preserves edits after failure", async () => {
    let reject!: (reason: Error) => void;
    mocks.batch.mockImplementation(
      () =>
        new Promise((_, fail) => {
          reject = fail;
        }),
    );
    setup();
    await chooseKnowledge();
    const a = await screen.findByRole("button", { name: "A" });
    fireEvent.click(a);
    const save = screen.getByRole("button", { name: "Save bindings" });
    fireEvent.click(save);
    await waitFor(() => expect(save).toBeDisabled());
    expect(a).toBeDisabled();
    await act(async () => reject(new Error("Binding update failed")));
    expect(await screen.findByRole("alert")).toHaveTextContent("Binding update failed");
    expect(a).toHaveAttribute("aria-pressed", "true");
    expect(save).toBeEnabled();
  });

  it("preselects all bindings, submits only edits, and preserves selection after a failed save", async () => {
    mocks.bindingNames.mockImplementation(async (knowledge) => ({
      knowledge_id: knowledge,
      characterNames: knowledge === "alpha" ? ["A", "off-page", "unavailable"] : [],
    }));
    mocks.batch.mockRejectedValue(new Error("Batch failed"));
    setup();
    await chooseKnowledge();
    const a = await screen.findByRole("button", { name: "A" });
    expect(a).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(a);
    fireEvent.click(screen.getByRole("button", { name: "B" }));
    fireEvent.click(screen.getByRole("button", { name: "Save bindings" }));
    await waitFor(() => expect(mocks.batch).toHaveBeenCalledWith("alpha", ["B"], ["A"]));
    expect(await screen.findByRole("alert")).toHaveTextContent("Batch failed");
    expect(a).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "B" })).toHaveAttribute("aria-pressed", "true");
    await chooseKnowledge("beta");
    await waitFor(() => expect(screen.getByRole("button", { name: "B" })).toHaveAttribute("aria-pressed", "false"));
    expect(screen.getByRole("button", { name: "Save bindings" })).toBeDisabled();
  });

  it("searches within the selected knowledge and clears back to browsing", async () => {
    setup();
    await chooseKnowledge();
    await screen.findByText("First page setting");
    fireEvent.change(screen.getByRole("textbox", { name: "Search entries" }), { target: { value: "fog" } });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/ }));
    expect(await screen.findByText("Fog result")).toBeInTheDocument();
    expect(mocks.search).toHaveBeenCalledWith("alpha", "fog");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(await screen.findByText("First page setting")).toBeInTheDocument();
    await chooseKnowledge("beta");
    await waitFor(() => expect(mocks.entries).toHaveBeenCalledWith("beta"));
    expect(screen.queryByText("First page setting")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Search entries" })).toHaveValue("");
  });
  it("adds a memory to an empty knowledge and preserves input on failure", async () => {
    setup();
    await chooseKnowledge("beta");
    const input = screen.getByRole("textbox", { name: "Entry content" });
    expect(screen.getByRole("button", { name: "Add entry" })).toBeDisabled();
    fireEvent.change(input, { target: { value: " New setting " } });
    mocks.add.mockRejectedValueOnce(new Error("write failed"));
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));
    await screen.findByText("write failed");
    expect(input).toHaveValue(" New setting ");
    await waitFor(() => expect(screen.getByRole("button", { name: "Add entry" })).toBeEnabled());
    const result = { knowledge_id: "beta", count: 1, memories: [{ id: "new", memory: "New setting" }] };
    mocks.add.mockResolvedValue(result);
    mocks.entries.mockResolvedValue(result);
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));
    await screen.findByText("New setting");
    expect(mocks.add).toHaveBeenLastCalledWith("beta", "New setting");
    expect(input).toHaveValue("");
  });

  it("confirms entry deletion and clamps the last page", async () => {
    setup();
    await chooseKnowledge();
    await screen.findByText("First page setting");
    fireEvent.click(
      within(screen.getByRole("region", { name: "Material information" })).getByRole("button", { name: "Next page" }),
    );
    await screen.findByText("Second page setting");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Second page setting");
    expect(mocks.remove).not.toHaveBeenCalled();
    const result = { knowledge_id: "alpha", count: 1, memories: [{ id: "0", memory: "First page setting" }] };
    mocks.remove.mockResolvedValue(result);
    mocks.entries.mockResolvedValue(result);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith("alpha", "8"));
    await screen.findByText("First page setting");
    expect(
      within(screen.getByRole("region", { name: "Material information" })).getByRole("button", {
        name: "Previous page",
      }),
    ).toBeDisabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("requires knowledge confirmation, blocks duplicate requests and permits retry after failure", async () => {
    setup();
    await chooseKnowledge();
    fireEvent.click(screen.getByRole("button", { name: "Delete material" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("alpha");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mocks.deleteKnowledge).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete material" }));
    let reject!: (error: Error) => void;
    mocks.deleteKnowledge.mockImplementationOnce(
      () =>
        new Promise((_, fail) => {
          reject = fail;
        }),
    );
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocks.deleteKnowledge).toHaveBeenCalledWith("alpha"));
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" })).toBeDisabled();
    await act(async () => reject(new Error("partial deletion")));
    await screen.findByText("partial deletion");
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled());
    mocks.deleteKnowledge.mockResolvedValue({
      ok: true,
      knowledge_id: "alpha",
      deletedEntryCount: 1,
      deletedBindingCount: 1,
    });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Delete material" })).not.toBeInTheDocument();
    expect(mocks.deleteKnowledge).toHaveBeenCalledTimes(2);
  });

  it("does not clear a newly selected knowledge when an earlier write completes", async () => {
    setup();
    await chooseKnowledge();
    let resolve!: (value: unknown) => void;
    mocks.add.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Entry content" }), {
      target: { value: "Alpha setting" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));
    await waitFor(() => expect(mocks.add).toHaveBeenCalledWith("alpha", "Alpha setting"));
    await chooseKnowledge("beta");
    await act(async () =>
      resolve({ knowledge_id: "alpha", count: 1, memories: [{ id: "a", memory: "Alpha setting" }] }),
    );
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Entry content" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Delete material" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("beta");
  });
});
