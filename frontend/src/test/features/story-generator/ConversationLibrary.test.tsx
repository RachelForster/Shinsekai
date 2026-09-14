import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
vi.mock("../../../entities/chat/repository", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../entities/chat/repository")>()),
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
    disabled,
  }: {
    historyPath: string;
    storyPath: string;
    conversationId?: string;
    disabled?: boolean;
  }) => (
    <button disabled={disabled} data-history={historyPath} data-story={storyPath} data-conversation={conversationId}>
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
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter>
          <ConversationLibrary onEdit={onEdit} onCreate={onCreate} />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { onEdit, onCreate, client };
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
  it("disables creation and all resume entries until closing completes", async () => {
    mocks.status.mockResolvedValue({ state: "closing" });
    mocks.list.mockResolvedValue([
      entry,
      { ...entry, id: "legacy", hasSettings: false },
      { ...entry, id: "story", kind: "story", storyPath: "/story.json" },
    ]);
    const { client, onCreate, onEdit } = page();
    await screen.findByRole("button", { name: "Continue chat" });
    const names = ["New chat", "Continue chat", "Configure and continue", "Resume story"];
    await waitFor(() => names.forEach((name) => expect(screen.getByRole("button", { name })).toBeDisabled()));
    names.forEach((name) => fireEvent.click(screen.getByRole("button", { name })));
    expect(mocks.launch).not.toHaveBeenCalled();
    expect(onCreate).not.toHaveBeenCalled();
    expect(onEdit).not.toHaveBeenCalled();
    mocks.status.mockResolvedValue({ state: "idle" });
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["chat", "runtime-status"] });
    });
    await waitFor(() => names.forEach((name) => expect(screen.getByRole("button", { name })).toBeEnabled()));
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
    expect(onEdit).toHaveBeenCalledWith("one", "normal");
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
  it("routes a story with a deleted character to its settings", async () => {
    mocks.list.mockResolvedValue([{ ...entry, kind: "story", hasSettings: false, requiresCharacterSelection: true }]);
    const { onEdit } = page();
    fireEvent.click(await screen.findByRole("button", { name: "Configure and continue" }));
    expect(onEdit).toHaveBeenCalledWith("one", "story");
    expect(screen.queryByRole("button", { name: "Resume story" })).not.toBeInTheDocument();
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
    expect(screen.getByRole("heading", { name: "Start a new chat, meow!" })).toBeVisible();
    expect(document.querySelector(".conversation-library__empty img")).toHaveAttribute(
      "src",
      "/chat-empty-catgirl.png",
    );
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(onCreate).toHaveBeenCalledOnce();
  });
});
