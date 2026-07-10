import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ModelDownloadDialog } from "../../../shared/ui";

const baseProps = {
  cancelLabel: "No",
  closeLabel: "Close",
  confirmLabel: "Download",
  onClose: vi.fn(),
  open: true,
  state: "confirm" as const,
  title: "Model download",
};

describe("ModelDownloadDialog", () => {
  it("renders reusable details and routes confirmation", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <ModelDownloadDialog
        {...baseProps}
        description="The model is missing."
        details={[
          { label: "Model", value: "small" },
          { label: "Repository", value: "owner/model" },
        ]}
        onClose={onClose}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Model download" })).toBeInTheDocument();
    expect(screen.getByText("owner/model")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "No" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows shared task progress while downloading", () => {
    render(
      <ModelDownloadDialog
        {...baseProps}
        state="downloading"
        statusMessage="Downloading model…"
        task={{
          createdAt: 1,
          id: "task-1",
          kind: "model-download",
          logs: [],
          message: "10 MB / 20 MB",
          phase: "download",
          progress: 0.5,
          result: null,
          status: "running",
          title: "Model download",
          updatedAt: 2,
        }}
      />,
    );

    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("10 MB / 20 MB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Downloading model…" })).toBeDisabled();
  });

  it("offers retry after a failure", () => {
    const onRetry = vi.fn();
    render(
      <ModelDownloadDialog {...baseProps} error="Network failed" onRetry={onRetry} retryLabel="Retry" state="error" />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Network failed");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
