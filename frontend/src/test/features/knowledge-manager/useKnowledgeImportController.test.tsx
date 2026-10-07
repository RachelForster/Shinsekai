import type { PropsWithChildren } from "react";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useKnowledgeImportController } from "../../../features/knowledge-manager/useKnowledgeImportController";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({ preview: vi.fn(), execute: vi.fn() }));
vi.mock("../../../entities/knowledge/repository", () => ({
  previewKnowledgeImport: mocks.preview,
  importKnowledge: mocks.execute,
}));

function Wrapper({ children }: PropsWithChildren) {
  return (
    <I18nProvider language="en">
      <ToastProvider>{children}</ToastProvider>
    </I18nProvider>
  );
}

describe("knowledge import browsing refresh", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.preview.mockResolvedValue({ chunkCount: 1, fileCount: 1 });
  });

  it.each([true, false])("refreshes after import settles, success=%s", async (success) => {
    if (success) mocks.execute.mockResolvedValue({ knowledge_id: "alpha", savedCount: 1 });
    else mocks.execute.mockRejectedValue(new Error("partial write failure"));
    const onSettled = vi.fn();
    const { result } = renderHook(
      () =>
        useKnowledgeImportController({
          ensureReady: async () => true,
          onSettled,
        }),
      { wrapper: Wrapper },
    );
    act(() => result.current.setImportKnowledgeId("alpha"));
    await act(async () => result.current.previewFiles([new File(["knowledge"], "knowledge.txt")]));
    await act(async () => result.current.confirmImport());
    expect(onSettled).toHaveBeenCalledWith("alpha");
  });

  it("discards a preview returned for an old knowledge", async () => {
    let resolve!: (value: unknown) => void;
    mocks.preview.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const { result } = renderHook(() => useKnowledgeImportController({ ensureReady: async () => true }), {
      wrapper: Wrapper,
    });
    act(() => result.current.setImportKnowledgeId("alpha"));
    let pending!: Promise<boolean>;
    act(() => {
      pending = result.current.previewFiles([new File(["knowledge"], "knowledge.txt")]);
    });
    act(() => result.current.setImportKnowledgeId("beta"));
    await act(async () => {
      resolve({ chunkCount: 1 });
      await pending;
    });
    expect(result.current.preview).toBeNull();
    expect(result.current.previewOpen).toBe(false);
    await act(async () => result.current.confirmImport());
    expect(mocks.execute).not.toHaveBeenCalled();
  });

  it("waits for readiness and keeps the preview when Knowledge is not ready", async () => {
    let resolve!: (ready: boolean) => void;
    const ensureReady = vi.fn(
      () =>
        new Promise<boolean>((done) => {
          resolve = done;
        }),
    );
    const { result } = renderHook(() => useKnowledgeImportController({ ensureReady }), { wrapper: Wrapper });
    act(() => result.current.setImportKnowledgeId("alpha"));
    await act(async () => result.current.previewFiles([new File(["knowledge"], "knowledge.txt")]));

    let pending!: ReturnType<typeof result.current.confirmImport>;
    act(() => {
      pending = result.current.confirmImport();
    });
    expect(result.current.importPending).toBe(true);
    expect(mocks.execute).not.toHaveBeenCalled();

    await act(async () => {
      resolve(false);
      await pending;
    });
    expect(result.current.importPending).toBe(false);
    expect(result.current.previewOpen).toBe(true);
    expect(result.current.taskOpen).toBe(false);
    expect(mocks.execute).not.toHaveBeenCalled();
  });
});
