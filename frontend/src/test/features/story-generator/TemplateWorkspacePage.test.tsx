import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { TemplateWorkspacePage } from "../../../features/template-workspace/TemplateWorkspacePage";
import { I18nProvider } from "../../../shared/i18n";
import { resolveConversationTitle } from "../../../entities/chat/conversationTitle";

vi.mock("../../../features/template-editor/TemplateEditorPage", () => ({
  TemplateEditorPage: ({
    conversationTitle,
    conversationId,
  }: {
    conversationTitle?: string;
    conversationId?: string;
  }) => (
    <div data-testid="normal-editor">
      {conversationTitle || conversationId}
      <input aria-label="Normal draft" />
    </div>
  ),
}));
vi.mock("../../../features/template-workspace/ConversationLibrary", () => ({
  ConversationLibrary: ({ onCreate, onEdit }: { onCreate: () => void; onEdit: (id: string, kind: string) => void }) => (
    <>
      <button onClick={onCreate}>New chat</button>
      <button onClick={() => onEdit("old-story", "story")}>Edit story</button>
    </>
  ),
}));
vi.mock("../../../features/story-generator/StoryGeneratorPage", () => ({
  StoryGeneratorPage: ({ conversationTitle }: { conversationTitle?: string }) => (
    <div data-testid="story-editor">{conversationTitle}</div>
  ),
}));
function renderPage(path = "/settings/templates") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <I18nProvider language="en">
        <TemplateWorkspacePage />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("chat workspace", () => {
  it("uses local time for empty titles and preserves user-supplied names", () => {
    const createdAt = new Date(2026, 0, 2, 3, 4, 5);
    expect(resolveConversationTitle(undefined, createdAt)).toBe("2026-01-02 03:04:05");
    expect(resolveConversationTitle("  ", createdAt)).toBe("2026-01-02 03:04:05");
    expect(resolveConversationTitle("  Evening walk  ", createdAt)).toBe("Evening walk");
  });
  it.each(["Normal chat", "Story chat"])("asks for title and type before configuring %s", async (kind) => {
    renderPage();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByTestId("normal-editor")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByRole("button", { name: "Next" })).toBeEnabled();
    fireEvent.change(dialog.getByLabelText("Chat title (optional)"), { target: { value: "  Evening walk  " } });
    fireEvent.click(dialog.getByRole("radio", { name: new RegExp(kind) }));
    fireEvent.click(dialog.getByRole("button", { name: "Next" }));
    expect(await screen.findByTestId(kind === "Normal chat" ? "normal-editor" : "story-editor")).toHaveTextContent(
      "Evening walk",
    );
    expect(screen.getByLabelText("Chat title (optional)")).toHaveValue("Evening walk");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
  it.each(["Normal chat", "Story chat"])("creates a timestamp title for an unnamed %s", async (kind) => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByLabelText("Chat title (optional)"), { target: { value: "  " } });
    fireEvent.click(dialog.getByRole("radio", { name: new RegExp(kind) }));
    fireEvent.click(dialog.getByRole("button", { name: "Next" }));
    const editor = await screen.findByTestId(kind === "Normal chat" ? "normal-editor" : "story-editor");
    expect(editor).toHaveTextContent(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    expect(screen.getByLabelText("Chat title (optional)")).toHaveValue(editor.textContent);
  });
  it("cancels creation without mounting an editor", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("normal-editor")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("keeps story deep links and uses the shared settings editor for existing stories", async () => {
    renderPage("/settings/templates?mode=story");
    expect(await screen.findByTestId("story-editor")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Chats" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit story" }));
    expect(await screen.findByTestId("normal-editor")).toHaveTextContent("old-story");
    expect(screen.getByText("Story chat")).toBeVisible();
    expect(screen.queryByLabelText("Chat title")).not.toBeInTheDocument();
  });
});
