import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCharacterMemoryImportController } from "../../../features/character-editor/useCharacterMemoryImportController";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mockImportCharacterMemories = vi.fn();
const mockPreviewCharacterMemoryImport = vi.fn();

vi.mock("../../../entities/character/repository", () => ({
  importCharacterMemories: (...args: unknown[]) => mockImportCharacterMemories(...args),
  previewCharacterMemoryImport: (...args: unknown[]) => mockPreviewCharacterMemoryImport(...args),
}));

const preview = {
  chunkCount: 2,
  dialogueCharacters: 8_000,
  dialogueLineCount: 80,
  estimatedInputTokens: 2_800,
  estimatedOutputTokens: 700,
  estimatedTotalTokens: 3_500,
  fileCount: 1,
  files: [
    {
      chunkCount: 2,
      dialogueCharacters: 8_000,
      dialogueLineCount: 80,
      kind: "json",
      name: "history.json",
      sourceTokens: 2_000,
    },
  ],
  sourceTokens: 2_000,
  warnings: [],
};

function Wrapper({ children }: PropsWithChildren) {
  return (
    <ToastProvider>
      <I18nProvider language="en">{children}</I18nProvider>
    </ToastProvider>
  );
}

describe("useCharacterMemoryImportController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPreviewCharacterMemoryImport.mockResolvedValue(preview);
    mockImportCharacterMemories.mockResolvedValue({
      chunkCount: 2,
      duplicateCount: 1,
      estimatedTotalTokens: 3_500,
      extractedCount: 4,
      fileCount: 1,
      savedCount: 3,
    });
  });

  it("previews selected files without importing until explicit confirmation", async () => {
    const ensureReady = vi.fn().mockResolvedValue(true);
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(
      () => useCharacterMemoryImportController({ ensureReady, memoryName: "Mika", onRefresh }),
      { wrapper: Wrapper },
    );

    await act(async () => {
      await result.current.openPicker();
    });
    expect(result.current.pickerOpen).toBe(true);
    expect(ensureReady).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.previewItems(["C:/history.json"]);
    });

    expect(mockPreviewCharacterMemoryImport).toHaveBeenCalledWith("Mika", ["C:/history.json"]);
    expect(result.current.preview).toEqual(preview);
    expect(result.current.previewOpen).toBe(true);
    expect(mockImportCharacterMemories).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.confirmImport();
    });

    expect(mockImportCharacterMemories).toHaveBeenCalledWith(
      "Mika",
      ["C:/history.json"],
      expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
    );
    expect(ensureReady).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
    expect(result.current.result?.savedCount).toBe(3);
    expect(result.current.taskOpen).toBe(true);
  });

  it("keeps the preview open and does not import when runtime readiness fails at confirmation", async () => {
    const ensureReady = vi.fn().mockResolvedValue(false);
    const { result } = renderHook(
      () => useCharacterMemoryImportController({ ensureReady, memoryName: "Mika", onRefresh: vi.fn() }),
      { wrapper: Wrapper },
    );

    await act(async () => {
      await result.current.openPicker();
    });

    expect(result.current.pickerOpen).toBe(true);
    expect(ensureReady).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.previewItems(["C:/history.json"]);
    });
    expect(result.current.previewOpen).toBe(true);

    await act(async () => {
      await result.current.confirmImport();
    });

    expect(ensureReady).toHaveBeenCalledTimes(1);
    expect(result.current.previewOpen).toBe(true);
    expect(result.current.importPending).toBe(false);
    expect(mockPreviewCharacterMemoryImport).toHaveBeenCalledWith("Mika", ["C:/history.json"]);
    expect(mockImportCharacterMemories).not.toHaveBeenCalled();
  });
});
