import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatInitializationDialog } from "../../../features/chat-startup/ChatInitializationDialog";
import { I18nProvider } from "../../../shared/i18n";

function renderDialog(props: Partial<Parameters<typeof ChatInitializationDialog>[0]> = {}) {
  const onClose = props.onClose ?? vi.fn();
  const result = render(
    <I18nProvider language="en">
      <ChatInitializationDialog
        onClose={onClose}
        open
        pending
        task={{
          createdAt: 1,
          id: "chat-init-1",
          kind: "chat-initialization",
          logs: ["TTS process started"],
          message: "Warming up the voice model",
          phase: "tts",
          progress: 0.5,
          result: null,
          status: "running",
          title: "Initialize chat",
          updatedAt: 2,
        }}
        {...props}
      />
    </I18nProvider>,
  );
  return { ...result, onClose };
}

describe("ChatInitializationDialog", () => {
  it("shows the catgirl animation and live task progress while initialization runs", () => {
    const { onClose } = renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Preparing chat" });

    expect(document.querySelector('img[src="/chat-init-catgirl.gif"]')).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Starting voice service");
    expect(dialog).toHaveTextContent("Warming up the voice model");
    expect(dialog).toHaveTextContent("50%");
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps initialization errors visible and allows the dialog to close", () => {
    const { onClose } = renderDialog({
      error: "TTS server did not start",
      pending: false,
      task: null,
    });

    expect(screen.getByRole("alert")).toHaveTextContent("TTS server did not start");
    expect(screen.getByText("Chat preparation failed", { selector: "strong" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Close" }).at(-1)!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
