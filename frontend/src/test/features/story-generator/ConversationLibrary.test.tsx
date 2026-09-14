import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConversationLibrary } from "../../../features/template-workspace/ConversationLibrary";
import { I18nProvider } from "../../../shared/i18n";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  prepare: vi.fn(),
  rename: vi.fn(),
  launch: vi.fn(),
  status: vi.fn(),
  show: vi.fn(),
  remove: vi.fn(),
}));
vi.mock("../../../entities/chat/repository", () => ({
  conversationsQueryKey: ["chat", "conversations"],
  chatQueryKey: ["chat"],
  listConversations: mocks.list,
  prepareConversation: mocks.prepare,
  renameConversation: mocks.rename,
  deleteConversation: mocks.remove,
  launchChat: mocks.launch,
  getChatRuntimeStatus: mocks.status,
}));
vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: async () => [],
}));
vi.mock("../../../features/story-generator/components/StoryLaunchButton", () => ({
  StoryLaunchButton: ({
    historyPath,
    storyPath,
    conversationId,
  }: {
    historyPath: string;
    storyPath: string;
    conversationId?: string;
  }) => (
    <button data-history={historyPath} data-story={storyPath} data-conversation={conversationId}>
      Resume story
    </button>
  ),
}));
vi.mock("../../../shared/desktop/chatWindow", () => ({ showChatSurface: mocks.show }));
vi.mock("../../../features/chat-startup/ChatInitializationDialog", () => ({ ChatInitializationDialog: () => null }));

const entry = {
  id: "one",
  title: "Evening",
  characters: ["Alice"],
  preview: "Good night",
  updatedAt: 1000,
  kind: "normal",
  hasSettings: true,
  historyPath: "/saved/one",
  storyPath: "",
};

function page() {
  const onEdit = vi.fn();
  const onCreate = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nProvider language="en">
        <MemoryRouter>
          <ConversationLibrary onEdit={onEdit} onCreate={onCreate} />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { onEdit, onCreate };
}

describe("conversation library", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue([entry]);
    mocks.status.mockResolvedValue({ state: "idle" });
    mocks.prepare.mockResolvedValue({
      characters: ["Alice"],
      historyPath: "/saved/one",
      scenario: "Original",
      resetHistory: false,
    });
    mocks.launch.mockResolvedValue({ sessionId: "runtime-one" });
    mocks.remove.mockResolvedValue(undefined);
  });
  it("offers settings and deletion for legacy normal and story chats", async () => {
    mocks.list.mockResolvedValue([
      { ...entry, hasSettings: false },
      { ...entry, id: "story", kind: "story", hasSettings: false },
    ]);
    const { onEdit } = page();
    const buttons = await screen.findAllByRole("button", { name: "Chat settings" });
    buttons.forEach((button) => fireEvent.click(button));
    expect(onEdit.mock.calls).toEqual([
      ["one", "normal"],
      ["story", "story"],
    ]);
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(2);
  });
  it("requires confirmation and refreshes the list after deletion", async () => {
    page();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(mocks.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByText(/Delete “Evening”/)).toBeVisible();
    mocks.list.mockResolvedValue([]);
    fireEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith("one"));
    await waitFor(() => expect(screen.queryByText("Evening")).not.toBeInTheDocument());
    expect(screen.getByText(/No chats yet/)).toBeVisible();
  });
  it("keeps the confirmation open and displays deletion errors", async () => {
    mocks.remove.mockRejectedValue(new Error("Close this chat before deleting it."));
    page();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Close this chat");
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByText("Evening")).toBeVisible();
  });
  it("continues the chosen record with its saved settings", async () => {
    page();
    expect(await screen.findByText("Good night")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Continue chat" }));
    await waitFor(() => expect(mocks.show).toHaveBeenCalled());
    expect(mocks.prepare).toHaveBeenCalledWith("one");
    expect(mocks.launch).toHaveBeenCalledWith(
      expect.objectContaining({ historyPath: "/saved/one", resetHistory: false, scenario: "Original" }),
      expect.anything(),
    );
  });
  it("does not silently launch an older record with unrelated settings", async () => {
    mocks.list.mockResolvedValue([{ ...entry, hasSettings: false }]);
    const { onEdit } = page();
    fireEvent.click(await screen.findByRole("button", { name: "Configure and continue" }));
    expect(onEdit).toHaveBeenCalledWith("one");
    expect(mocks.launch).not.toHaveBeenCalled();
  });
  it("keeps multiple saves of the same story distinct", async () => {
    mocks.list.mockResolvedValue(
      [1, 2].map((id) => ({
        ...entry,
        id: `story-${id}`,
        kind: "story",
        storyPath: "/story.json",
        historyPath: `/play-${id}`,
      })),
    );
    page();
    const buttons = await screen.findAllByRole("button", { name: "Resume story" });
    expect(buttons.map((button) => button.dataset.history)).toEqual(["/play-1", "/play-2"]);
    expect(buttons.map((button) => button.dataset.conversation)).toEqual(["story-1", "story-2"]);
  });
  it("renames the record without starting or switching chats", async () => {
    page();
    fireEvent.click(await screen.findByRole("button", { name: "Rename" }));
    const dialog = screen.getByRole("dialog", { name: "Rename" });
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Library evening" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mocks.rename).toHaveBeenCalledWith("one", "Library evening"));
    expect(mocks.launch).not.toHaveBeenCalled();
  });
  it("keeps an active runtime from being confused with the selected record", async () => {
    mocks.status.mockResolvedValue({ state: "running" });
    page();
    fireEvent.click(await screen.findByRole("button", { name: "Continue chat" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(mocks.prepare).not.toHaveBeenCalled();
  });
  it("provides a creation action when history is empty", async () => {
    mocks.list.mockResolvedValue([]);
    const { onCreate } = page();
    expect(await screen.findByText(/No chats yet/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(onCreate).toHaveBeenCalledOnce();
  });
});
