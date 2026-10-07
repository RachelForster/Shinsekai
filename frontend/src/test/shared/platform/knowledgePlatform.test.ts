import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpPlatform } from "../../../shared/platform/httpPlatform";
import { createBrowserPreviewPlatform } from "../../../shared/platform/browserPreviewPlatform";

describe("knowledge platform", () => {
  it("preview character renames migrate bindings and deletion clears them while keeping entries", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();
    const api = platform.knowledge;
    async function settle<T>(promise: Promise<T>): Promise<T> {
      await vi.advanceTimersByTimeAsync(3000);
      return promise;
    }
    const character = structuredClone((await settle(platform.characters.list()))[0]);
    const oldName = character.name;
    const newName = "Renamed material subscriber";
    const existingBindings = await settle(api.listKnowledgeBindings(oldName));
    for (const binding of existingBindings.bindings) {
      await settle(api.removeKnowledgeBinding(oldName, binding.knowledge_id));
    }
    await settle(api.addKnowledgeBinding(oldName, "rename-a"));
    await settle(api.addKnowledgeBinding(oldName, "rename-b"));
    await settle(api.addKnowledgeBinding(newName, "rename-a"));
    await settle(api.addKnowledgeBinding("Other", "rename-a"));
    await settle(api.addKnowledgeEntry("rename-a", "Preserved entry"));
    await settle(platform.characters.save({ ...character, name: newName }, oldName));
    expect(await settle(api.listKnowledgeBindings(oldName))).toMatchObject({ count: 0 });
    expect(await settle(api.listKnowledgeBindings(newName))).toMatchObject({
      count: 2,
      bindings: [{ knowledge_id: "rename-a" }, { knowledge_id: "rename-b" }],
    });
    expect(await settle(api.listKnowledgeBindingNames("rename-b"))).toMatchObject({ characterNames: [newName] });
    expect(await settle(api.listKnowledgeBindingNames("rename-a"))).toMatchObject({
      characterNames: ["Other", newName].sort(),
    });
    await platform.characters.delete(newName);
    expect(await settle(api.listKnowledgeBindings(newName))).toMatchObject({ count: 0 });
    expect(await settle(api.listKnowledgeBindingNames("rename-a"))).toMatchObject({ characterNames: ["Other"] });
    expect(await settle(api.listKnowledgeEntries("rename-a"))).toMatchObject({
      memories: [{ memory: "Preserved entry" }],
    });
    expect(await settle(api.listKnowledgeInstances({ query: "rename-b", page: 1 }))).toMatchObject({ count: 0 });
  });

  it("preview searches material IDs without matching entry contents", async () => {
    vi.useFakeTimers();
    const api = createBrowserPreviewPlatform().knowledge;
    async function settle<T>(promise: Promise<T>): Promise<T> {
      await vi.advanceTimersByTimeAsync(3000);
      return promise;
    }
    await settle(api.addKnowledgeEntry("search-alpha", "雾港试验资料 Bell"));
    await settle(api.addKnowledgeEntry("search-alpha", "雾港试验资料 bell tower"));
    await settle(api.addKnowledgeEntry("search-beta", "雾港试验资料 BELL"));
    const result = await settle(api.listKnowledgeInstances({ query: "  SEARCH-  ", page: 1 }));
    expect(result).toMatchObject({
      count: 2,
      knowledge: [
        { knowledge_id: "search-alpha", entryCount: 2 },
        { knowledge_id: "search-beta", entryCount: 1 },
      ],
    });
    expect(await settle(api.listKnowledgeInstances({ query: "雾港试验资料", page: 1 }))).toMatchObject({ count: 0 });
    expect(await settle(api.listKnowledgeInstances({ query: "SEARCH-ALPHA", page: 1 }))).toMatchObject({ count: 1 });
    expect(await settle(api.listKnowledgeInstances({ query: "no-matching-content", page: 1 }))).toMatchObject({
      count: 0,
      knowledge: [],
    });
  });

  it("loads all binding names and submits a batch delta", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ knowledge_id: "a&b", characterNames: ["A"] }) });
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpPlatform("http://localhost:8787").knowledge;
    await api.listKnowledgeBindingNames("a&b");
    await api.batchKnowledgeBindings("a&b", ["A", "B"], ["C"]);
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8787/api/knowledge/bindings/knowledge?knowledge_id=a%26b",
    );
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      knowledge_id: "a&b",
      add: ["A", "B"],
      remove: ["C"],
    });
  });

  it("preview batch updates preserve unrelated bindings and support retries", async () => {
    vi.useFakeTimers();
    const api = createBrowserPreviewPlatform().knowledge;
    const first = api.batchKnowledgeBindings("batch-knowledge", ["A", "B"], []);
    await vi.advanceTimersByTimeAsync(3000);
    await first;
    for (let i = 0; i < 2; i++) {
      const save = api.batchKnowledgeBindings("batch-knowledge", ["C"], ["A"]);
      await vi.advanceTimersByTimeAsync(3000);
      expect(await save).toMatchObject({ characterNames: ["B", "C"] });
    }
    const names = api.listKnowledgeBindingNames("batch-knowledge");
    await vi.advanceTimersByTimeAsync(3000);
    expect(await names).toEqual({ knowledge_id: "batch-knowledge", characterNames: ["B", "C"] });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("uploads knowledge files without a character and follows the import task", async () => {
    vi.useFakeTimers();
    const result = { knowledge_id: "A & B", savedCount: 1 };
    const running = { id: "knowledge-import-1", status: "running", kind: "knowledge-import" };
    const completed = { ...running, status: "succeeded", result };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ fileCount: 1 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => running })
      .mockResolvedValueOnce({ ok: true, json: async () => completed });
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpPlatform("http://localhost:8787").knowledge;
    const file = new File(["setting"], "knowledge.txt", { type: "text/plain" });
    await api.previewKnowledgeImport("A & B", [file]);
    const onTaskUpdate = vi.fn();
    const importing = api.importKnowledge("A & B", [file], { onTaskUpdate });
    await vi.advanceTimersByTimeAsync(3000);
    expect(await importing).toEqual(result);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8787/api/knowledge/import-preview-upload?knowledge_id=A%20%26%20B",
      "http://localhost:8787/api/knowledge/import-upload?knowledge_id=A%20%26%20B",
      "http://localhost:8787/api/tasks/knowledge-import-1",
    ]);
    expect(fetchMock.mock.calls[0][1].body).toBeInstanceOf(FormData);
    expect(fetchMock.mock.calls[1][1].body).toBeInstanceOf(FormData);
    expect(onTaskUpdate).toHaveBeenNthCalledWith(1, running);
    expect(onTaskUpdate).toHaveBeenNthCalledWith(2, completed);
  });

  it("checks Knowledge status with explicit start and retry options", async () => {
    const status = { status: "loading", modelCached: true };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => status });
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpPlatform("http://localhost:8787").knowledge;

    expect(await api.getKnowledgeStatus!()).toEqual(status);
    await api.getKnowledgeStatus!({ startLoading: true, retry: false });
    await api.getKnowledgeStatus!({ startLoading: false, retry: true });

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init.method, JSON.parse(init.body)])).toEqual([
      ["http://localhost:8787/api/knowledge/status", "POST", { startLoading: false, retry: false }],
      ["http://localhost:8787/api/knowledge/status", "POST", { startLoading: true, retry: false }],
      ["http://localhost:8787/api/knowledge/status", "POST", { startLoading: false, retry: true }],
    ]);
  });

  it("reports Knowledge ready in the browser preview without HTTP requests", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const status = createBrowserPreviewPlatform().knowledge.getKnowledgeStatus!({ startLoading: true });
    await vi.advanceTimersByTimeAsync(3000);
    expect(await status).toEqual({ status: "ready" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("encodes knowledge IDs and lists entries and searches independently of chat recall", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ memories: [], count: 0 }) });
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpPlatform("http://localhost:8787").knowledge;
    await api.listKnowledgeInstances!({ query: "雾港 & A", page: 2, refresh: true });
    await api.listKnowledgeEntries!("雾港 & A");
    await api.searchKnowledgeEntries!("雾港 & A", "钟声");
    const first = new URL(fetchMock.mock.calls[0][0]);
    expect(first.pathname).toBe("/api/knowledge/instances");
    expect(first.searchParams.get("query")).toBe("雾港 & A");
    expect(first.searchParams.get("page")).toBe("2");
    const entries = new URL(fetchMock.mock.calls[1][0]);
    expect(entries.searchParams.get("knowledge_id")).toBe("雾港 & A");
    expect(entries.searchParams.has("cursor")).toBe(false);
    expect(fetchMock.mock.calls[2][0]).toBe("http://localhost:8787/api/knowledge/entries/search");
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({
      knowledge_id: "雾港 & A",
      query: "钟声",
      limit: 200,
    });
  });

  it("preview import creates browsable entries without subscribing characters", async () => {
    vi.useFakeTimers();
    const api = createBrowserPreviewPlatform().knowledge;
    const importPromise = api.importKnowledge("new-knowledge", [
      new File(["setting"], "knowledge.txt", { type: "text/plain" }),
    ]);
    await vi.advanceTimersByTimeAsync(3000);
    await importPromise;
    const catalogPromise = api.listKnowledgeInstances!({ query: "new-knowledge", page: 1 });
    const bindingsPromise = api.listKnowledgeBindingNames("new-knowledge");
    const entriesPromise = api.listKnowledgeEntries!("new-knowledge");
    await vi.advanceTimersByTimeAsync(3000);
    expect(await catalogPromise).toMatchObject({
      knowledge: [{ knowledge_id: "new-knowledge", entryCount: 1, characterCount: 0 }],
    });
    expect(await bindingsPromise).toMatchObject({ characterNames: [] });
    expect(await entriesPromise).toMatchObject({
      memories: [{ memory: "Knowledge imported from knowledge.txt" }],
    });
    const pagePromise = api.listKnowledgeEntries!("preview-knowledge");
    await vi.advanceTimersByTimeAsync(3000);
    const result = await pagePromise;
    expect(result).toHaveProperty("count");
    expect(result).not.toHaveProperty("nextCursor");
    expect("memories" in result && result.memories.length).toBeGreaterThan(8);
  });
  it("dispatches binding CRUD and whole-knowledge deletion", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpPlatform("http://localhost:8787").knowledge;
    await api.listKnowledgeBindings!("A & B", 2);
    await api.addKnowledgeBinding!("A", "w");
    await api.removeKnowledgeBinding!("A", "w");
    await api.deleteKnowledge!("z");
    const query = new URL(fetchMock.mock.calls[0][0]);
    expect(query.pathname).toBe("/api/knowledge/bindings");
    expect(query.searchParams.get("character_name")).toBe("A & B");
    expect(query.searchParams.get("page")).toBe("2");
    const expected = [
      ["bindings/add", { character_name: "A", knowledge_id: "w" }],
      ["bindings/remove", { character_name: "A", knowledge_id: "w" }],
      ["delete", { knowledge_id: "z" }],
    ];
    expected.forEach(([path, body], index) => {
      const [url, init] = fetchMock.mock.calls[index + 1];
      expect(url).toBe(`http://localhost:8787/api/knowledge/${path}`);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body)).toEqual(body);
    });
  });

  it("preview binding changes and deletion preserve other knowledge", async () => {
    vi.useFakeTimers();
    const api = createBrowserPreviewPlatform().knowledge;
    async function settle<T>(promise: Promise<T>): Promise<T> {
      await vi.advanceTimersByTimeAsync(3000);
      return promise;
    }
    await settle(api.addKnowledgeBinding!("A", "w"));
    await settle(api.addKnowledgeBinding!("A", "w"));
    await settle(api.addKnowledgeBinding!("B", "w"));
    await settle(api.addKnowledgeBinding!("A", "z"));
    expect(await settle(api.listKnowledgeBindings!("A"))).toMatchObject({ count: 2 });
    await settle(api.removeKnowledgeBinding!("A", "w"));
    expect(await settle(api.listKnowledgeBindingNames("w"))).toMatchObject({ characterNames: ["B"] });
    expect(await settle(api.removeKnowledgeBinding!("B", "w"))).toMatchObject({ deleted: true });
    expect(await settle(api.removeKnowledgeBinding!("B", "w"))).toMatchObject({ deleted: false });
    expect(await settle(api.removeKnowledgeBinding!("A", "z"))).toMatchObject({ deleted: true });
    await settle(api.importKnowledge("new-knowledge", [new File(["setting"], "knowledge.txt")]));
    expect(await settle(api.deleteKnowledge!("new-knowledge"))).toEqual({
      ok: true,
      knowledge_id: "new-knowledge",
      deletedEntryCount: 1,
      deletedBindingCount: 0,
    });
    expect(await settle(api.listKnowledgeBindings!("A"))).toMatchObject({ count: 0 });
    expect(await settle(api.listKnowledgeEntries!("preview-knowledge"))).toMatchObject({ count: 18 });
    expect(await settle(api.deleteKnowledge!("new-knowledge"))).toMatchObject({
      deletedEntryCount: 0,
      deletedBindingCount: 0,
    });
    await expect(api.deleteKnowledge!(" ")).rejects.toThrow("knowledge id");
  });
  it("sends entry mutations with their knowledge and record IDs", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ memories: [], count: 0 }) });
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpPlatform("http://localhost:8787").knowledge;
    await api.addKnowledgeEntry!("雾港", "setting");
    await api.deleteKnowledgeEntry!("雾港", "entry-id");
    expect(fetchMock.mock.calls.map(([url, init]) => [url, init.method, JSON.parse(init.body)])).toEqual([
      ["http://localhost:8787/api/knowledge/remember-and-list", "POST", { knowledge_id: "雾港", content: "setting" }],
      ["http://localhost:8787/api/knowledge/forget-and-list", "POST", { knowledge_id: "雾港", memory_id: "entry-id" }],
    ]);
  });

  it("adds and deletes preview entries without deleting bindings or other knowledge", async () => {
    vi.useFakeTimers();
    const api = createBrowserPreviewPlatform().knowledge;
    async function settle<T>(promise: Promise<T>): Promise<T> {
      await vi.advanceTimersByTimeAsync(3000);
      return promise;
    }
    await settle(api.addKnowledgeBinding!("A", "w"));
    const added = await settle(api.addKnowledgeEntry!("w", "setting"));
    if (!("memories" in added)) throw new Error("unexpected runtime status");
    expect(added.memories).toHaveLength(1);
    expect(await settle(api.addKnowledgeEntry!("w", "setting"))).toMatchObject({ count: 1 });
    expect(await settle(api.deleteKnowledgeEntry!("w", added.memories[0].id))).toMatchObject({ count: 0 });
    expect(await settle(api.listKnowledgeBindings!("A"))).toMatchObject({ count: 1 });
    expect(await settle(api.listKnowledgeEntries!("preview-knowledge"))).toMatchObject({ count: 18 });
  });
});
