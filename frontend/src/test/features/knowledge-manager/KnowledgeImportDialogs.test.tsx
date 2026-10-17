import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeImportDialogs } from "../../../features/knowledge-manager/KnowledgeDialogs";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

describe("KnowledgeImportDialogs", () => {
  it("shows material target, token estimates, file details, and requires explicit confirmation", () => {
    const onConfirm = vi.fn();

    render(
      <I18nProvider language="en">
        <KnowledgeImportDialogs
          knowledgeId="harbor"
          importPending={false}
          onClosePreview={vi.fn()}
          onCloseTask={vi.fn()}
          onConfirm={onConfirm}
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
                kind: "txt",
                name: "knowledge.txt",
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
    expect(screen.getByText(/harbor/)).toBeInTheDocument();
    expect(screen.getByText("knowledge.txt")).toBeInTheDocument();
    expect(screen.getByText("Source text")).toBeInTheDocument();
    expect(screen.queryByText(/JSON history is first converted/)).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
