import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { CurrentConversationEditorDialog } from "../../../features/chat-workspace/CurrentConversationEditorDialog";
import { I18nProvider } from "../../../shared/i18n";
const { getCurrentConversation } = vi.hoisted(() => ({ getCurrentConversation: vi.fn() }));

vi.mock("../../../entities/chat/repository", () => ({
  conversationsQueryKey: ["chat", "conversations"],
  getCurrentConversation,
}));
vi.mock("../../../features/story-generator/StoryConversationSettings", () => ({
  StoryConversationSettings: () => <div>Dedicated story settings</div>,
}));
vi.mock("../../../features/template-editor/TemplateEditorPage", () => ({
  TemplateEditorPage: ({
    conversationId,
    onPendingChange,
    onApplied,
  }: {
    conversationId: string;
    onPendingChange: (pending: boolean) => void;
    onApplied: (snapshot: unknown) => void;
  }) => (
    <>
      <span>{conversationId}</span>
      <button onClick={() => onPendingChange(true)}>Apply</button>
      <button onClick={() => onApplied({ historyPath: "same-history" })}>Complete</button>
    </>
  ),
}));

function page() {
  const onClose = vi.fn();
  const onApplied = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider language="en">
        <CurrentConversationEditorDialog onClose={onClose} onApplied={onApplied} />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { onClose, onApplied };
}

describe("current conversation editor", () => {
  it("shows the current story label and can close without applying", async () => {
    getCurrentConversation.mockResolvedValue({ id: "current", title: "Chapter two", kind: "story" });
    const { onClose, onApplied } = page();
    expect(await screen.findByText("Story chat")).toBeVisible();
    expect(screen.getByText("Chapter two")).toBeVisible();
    expect(screen.getByText("Dedicated story settings")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onApplied).not.toHaveBeenCalled();
  });
  it("keeps initialization mounted until apply finishes", async () => {
    getCurrentConversation.mockResolvedValue({ id: "current", title: "Normal chat", kind: "normal" });
    const { onClose, onApplied } = page();
    fireEvent.click(await screen.findByRole("button", { name: "Apply" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument());
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    expect(onApplied).toHaveBeenCalledWith({ historyPath: "same-history" });
  });
});
