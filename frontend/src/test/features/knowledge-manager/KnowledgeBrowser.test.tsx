import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
});
