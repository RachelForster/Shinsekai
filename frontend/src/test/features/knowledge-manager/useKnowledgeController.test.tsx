import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useKnowledgeController } from "../../../features/knowledge-manager/useKnowledgeController";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({ entries: vi.fn(), instances: vi.fn(), status: vi.fn() }));
vi.mock("../../../entities/knowledge/repository", () => ({
  getKnowledgeStatus: mocks.status,
  listKnowledgeEntries: mocks.entries,
  listKnowledgeInstances: mocks.instances,
  searchKnowledgeEntries: vi.fn(),
  KnowledgeBrowseError: class extends Error {
    status = "error";
  },
}));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <ToastProvider>{children}</ToastProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
  return { client, wrapper };
}

it("pages eight entries locally and clamps the page after a shorter refresh", async () => {
  const rows = Array.from({ length: 17 }, (_, i) => ({ id: String(i), memory: `entry ${i}` }));
  mocks.entries.mockResolvedValue({ knowledge_id: "alpha", count: rows.length, memories: rows });
  const { client, wrapper } = createWrapper();
  const { result, unmount } = renderHook(() => useKnowledgeController(), { wrapper });
  act(() => result.current.selectKnowledge("alpha"));
  await waitFor(() => expect(result.current.memories).toHaveLength(8));
  act(() => result.current.entriesView.next());
  expect(result.current.memories[0].id).toBe("8");
  act(() => result.current.entriesView.next());
  expect(result.current.memories).toEqual([rows[16]]);
  expect(result.current.entriesView.hasNext).toBe(false);
  expect(mocks.entries).toHaveBeenCalledTimes(1);
  act(() =>
    client.setQueryData(["knowledge", "entries", "alpha"], {
      knowledge_id: "alpha",
      count: 1,
      memories: [rows[0]],
    }),
  );
  await waitFor(() => expect(result.current.entriesView.page).toBe(1));
  expect(result.current.memories).toEqual([rows[0]]);
  unmount();
  client.clear();
});

it("only requests a runtime retry after an explicit refresh", async () => {
  mocks.status.mockResolvedValue({ status: "ready" });
  mocks.entries.mockResolvedValue({ knowledge_id: "alpha", count: 0, memories: [] });
  mocks.instances.mockClear();
  mocks.instances.mockResolvedValue({ knowledge: [], count: 0, page: 1, pageSize: 20 });
  const { client, wrapper } = createWrapper();
  const { result, unmount } = renderHook(() => useKnowledgeController(), { wrapper });
  act(() => result.current.selectKnowledge("alpha"));
  act(() => result.current.toggleInstances());
  await waitFor(() => expect(mocks.instances).toHaveBeenCalled());
  expect(mocks.instances.mock.calls.every(([input]) => input.refresh !== true)).toBe(true);
  await act(async () => {
    await result.current.refresh();
  });
  expect(mocks.instances).toHaveBeenCalledWith({ query: "", page: 1, refresh: true });
  unmount();
  client.clear();
});

describe("material catalog search", () => {
  beforeEach(() => {
    mocks.instances.mockReset();
    mocks.instances.mockResolvedValue({ knowledge: [], count: 0, page: 1, pageSize: 20 });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces input and cancels scheduled searches when dismissed or unmounted", async () => {
    vi.useFakeTimers();
    const { client, wrapper } = createWrapper();
    const { result, unmount } = renderHook(() => useKnowledgeController(), { wrapper });
    act(() => result.current.changeKnowledgeQuery("old"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    act(() => result.current.changeKnowledgeQuery(" new "));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(mocks.instances).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mocks.instances).toHaveBeenCalledTimes(1);
    expect(mocks.instances).toHaveBeenCalledWith({ query: "new", page: 1 });
    act(() => result.current.changeKnowledgeQuery("dismissed"));
    act(() => result.current.setInstancePickerOpen(false));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(result.current.instancePickerOpen).toBe(false);
    expect(mocks.instances).toHaveBeenCalledTimes(1);
    act(() => result.current.changeKnowledgeQuery("unmounted"));
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(mocks.instances).toHaveBeenCalledTimes(1);
    client.clear();
  });
});

describe("Knowledge readiness", () => {
  beforeEach(() => {
    mocks.status.mockReset();
    mocks.instances.mockReset();
    mocks.instances.mockResolvedValue({ knowledge: [], count: 0, page: 1, pageSize: 20 });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows loading progress and keeps monitoring after the dialog is closed", async () => {
    const task = { id: "knowledge-model", status: "running", phase: "initialize", progress: 0.5 };
    mocks.status
      .mockResolvedValueOnce({ status: "loading", modelCached: true, task })
      .mockResolvedValueOnce({ status: "ready" });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useKnowledgeController(), { wrapper });
    let pending!: Promise<boolean>;
    await act(async () => {
      pending = result.current.ensureKnowledgeModelReady();
    });
    expect(result.current.modelLoadingOpen).toBe(true);
    expect(result.current.modelLoadingTask).toEqual(task);
    expect(result.current.modelLoadingMessage).toBe("Loading embedding model…");
    act(() => result.current.closeLoadingDialog());
    expect(result.current.modelLoadingOpen).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      expect(await pending).toBe(true);
    });
    expect(result.current.modelChecking).toBe(false);
  });

  it("starts an uninitialized runtime and then observes it without repeated retries", async () => {
    mocks.status
      .mockResolvedValueOnce({ status: "not_started", modelCached: false })
      .mockResolvedValueOnce({ status: "loading", modelCached: false })
      .mockResolvedValueOnce({ status: "ready" });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useKnowledgeController(), { wrapper });
    let pending!: Promise<boolean>;
    await act(async () => {
      pending = result.current.ensureKnowledgeModelReady();
    });
    expect(result.current.modelLoadingMessage).toBe("Downloading embedding model…");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      expect(await pending).toBe(true);
    });
    expect(mocks.status.mock.calls).toEqual([
      [{ startLoading: true, retry: false }],
      [{ startLoading: true, retry: false }],
      [{ startLoading: false, retry: false }],
    ]);
  });

  it("shares concurrent refreshes and waits for readiness before refreshing data", async () => {
    mocks.status
      .mockResolvedValueOnce({ status: "loading", modelCached: true })
      .mockResolvedValueOnce({ status: "ready" });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useKnowledgeController(), { wrapper });
    let pending!: Promise<void>;
    await act(async () => {
      pending = result.current.refresh();
    });
    expect(result.current.refreshPending).toBe(true);
    expect(result.current.refresh()).toBe(pending);
    expect(mocks.instances).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      await pending;
    });
    expect(mocks.status).toHaveBeenNthCalledWith(1, { startLoading: true, retry: true });
    expect(mocks.status).toHaveBeenNthCalledWith(2, { startLoading: false, retry: false });
    expect(mocks.instances).toHaveBeenCalledTimes(1);
    expect(mocks.instances).toHaveBeenCalledWith({ query: "", page: 1, refresh: true });
    expect(result.current.refreshPending).toBe(false);
  });

  it("stops polling and skips refresh work after unmount", async () => {
    mocks.status.mockResolvedValue({ status: "loading", modelCached: true });
    const { wrapper } = createWrapper();
    const { result, unmount } = renderHook(() => useKnowledgeController(), { wrapper });
    let pending!: Promise<void>;
    await act(async () => {
      pending = result.current.refresh();
    });
    unmount();
    await pending;
    await vi.advanceTimersByTimeAsync(3000);
    expect(mocks.status).toHaveBeenCalledTimes(1);
    expect(mocks.instances).not.toHaveBeenCalled();
  });
});
