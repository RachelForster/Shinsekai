import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterMemoryImportDialogs } from "../../../features/character-editor/CharacterMemoryImportDialogs";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

describe("CharacterMemoryImportDialogs", () => {
  it("shows token estimates, request count, JSON conversion, and requires explicit confirmation", () => {
    const onConfirm = vi.fn();

    render(
      <I18nProvider language="en">
        <CharacterMemoryImportDialogs
          importPending={false}
          onClosePicker={vi.fn()}
          onClosePreview={vi.fn()}
          onCloseTask={vi.fn()}
          onConfirm={onConfirm}
          onSelect={vi.fn()}
          pickerOpen={false}
          preview={{
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
          }}
          previewOpen
          result={null}
          task={null}
          taskOpen={false}
        />
      </I18nProvider>,
    );

    expect(screen.getByText(/about 3,500 tokens across 2 chunks/)).toBeInTheDocument();
    expect(screen.getByText("2 chunks / about 2 model requests")).toBeInTheDocument();
    expect(screen.getByText(/Actual token usage and cost vary/)).toBeInTheDocument();
    expect(screen.getByText(/JSON history is first converted/)).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm and extract" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
