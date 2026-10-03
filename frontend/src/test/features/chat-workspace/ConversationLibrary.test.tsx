import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConversationLibrary } from "../../../features/chat-workspace/ConversationLibrary";
import { I18nProvider } from "../../../shared/i18n";
import { ToastProvider } from "../../../shared/ui";
import { setMobileAccessPreference } from "../../../features/mobile-access/useMobileAccessPreference";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  prepare: vi.fn(),
  rename: vi.fn(),
  launch: vi.fn(),
  status: vi.fn(),
  show: vi.fn(),
  remove: vi.fn(),
  snapshot: vi.fn(),
  current: vi.fn(),
  close: vi.fn(),
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
  getChatSnapshot: mocks.snapshot,
  getCurrentConversation: mocks.current,
  closeChat: mocks.close,
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

const mobileAccess = {
  enabled: true,
  host: "192.168.1.20",
  httpPort: 8789,
  websocketPort: 8790,
  qrCodeDataUrl: "data:image/png;base64,dGVzdA==",
  url: "http://192.168.1.20:8789/",
  websocketUrl: "ws://192.168.1.20:8790/ws",
};
const runningSnapshot = { sessionId: "runtime-one", runtimeMode: "react", chatProcessRunning: true, mobileAccess };

function page() {
  const onEdit = vi.fn();
  const onCreate = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter>
          <ToastProvider>
            <ConversationLibrary onEdit={onEdit} onCreate={onCreate} />
          </ToastProvider>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { onEdit, onCreate, client };
}

describe("conversation library", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
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
    mocks.snapshot.mockResolvedValue(runningSnapshot);
    mocks.current.mockResolvedValue(entry);
    mocks.close.mockResolvedValue({ ...runningSnapshot, chatProcessRunning: false, mobileAccess: undefined });
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
  it("places the mobile switch immediately before New chat in the management toolbar", async () => {
    page();
    await screen.findByText("Good night");
    const toggle = screen.getByRole("checkbox", { name: "Connect phone" });
    const toolbar = toggle.closest(".conversation-library__toolbar") as HTMLElement;
    const create = within(toolbar).getByRole("button", { name: "New chat" });
    expect(toggle).not.toBeChecked();
    expect(toggle.compareDocumentPosition(create) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(toggle).toHaveAccessibleDescription(/Applies when creating or resuming the next chat/);
    expect(mocks.launch).not.toHaveBeenCalled();
  });
  it("keeps the mobile option available when there are no chats yet", async () => {
    mocks.list.mockResolvedValue([]);
    page();
    await screen.findByText(/No chats yet/);
    const toggle = screen.getByRole("checkbox", { name: "Connect phone" });
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
    expect(screen.getByRole("button", { name: "New chat" })).toBeEnabled();
    expect(mocks.launch).not.toHaveBeenCalled();
  });
  it.each([false, true])(
    "uses the toolbar preference %s rather than an old chat's saved mobile flag",
    async (enabled) => {
      setMobileAccessPreference(enabled);
      mocks.prepare.mockResolvedValueOnce({ historyPath: "/saved/one", enableMobileAccess: !enabled });
      page();
      fireEvent.click(await screen.findByRole("button", { name: "Continue chat" }));
      await waitFor(() =>
        expect(mocks.launch).toHaveBeenCalledWith(
          expect.objectContaining({ enableMobileAccess: enabled, historyPath: "/saved/one" }),
          expect.anything(),
        ),
      );
    },
  );
  it("shows the existing QR dialog when continuing a chat with mobile access", async () => {
    mocks.launch.mockResolvedValueOnce({
      mobileAccess: {
        enabled: true,
        host: "192.168.1.20",
        httpPort: 8789,
        websocketPort: 8790,
        qrCodeDataUrl: "data:image/png;base64,dGVzdA==",
        url: "http://192.168.1.20:8789/",
        websocketUrl: "ws://192.168.1.20:8790/ws",
      },
    });
    page();
    fireEvent.click(screen.getByRole("checkbox", { name: "Connect phone" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue chat" }));
    const dialog = await screen.findByRole("dialog", { name: "Mobile access is ready" });
    expect(within(dialog).getByRole("img", { name: "QR code for mobile chat access" })).toBeVisible();
    expect(mocks.show).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Open local chat" }));
    await waitFor(() =>
      expect(mocks.show).toHaveBeenCalledWith(
        expect.objectContaining({
          snapshot: { runtimeMode: "react", wsUrl: "ws://192.168.1.20:8790/ws" },
        }),
      ),
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
    expect(await screen.findByRole("heading", { name: "Currently chatting: Evening" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue chat" })).toBeDisabled();
    expect(mocks.prepare).not.toHaveBeenCalled();
  });
  it("keeps the active controls after closing the launch QR and can show it again", async () => {
    mocks.launch.mockImplementationOnce(async () => {
      mocks.status.mockResolvedValue({ state: "running" });
      return runningSnapshot;
    });
    page();
    fireEvent.click(await screen.findByRole("button", { name: "Continue chat" }));
    const qr = await screen.findByRole("dialog", { name: "Mobile access is ready" });
    fireEvent.click(within(qr).getByRole("button", { name: "Close" }));
    expect(await screen.findByRole("heading", { name: "Currently chatting: Evening" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Show QR code" }));
    const reopened = await screen.findByRole("dialog", { name: "Mobile access is ready" });
    expect(within(reopened).getByRole("img")).toHaveAttribute("src", mobileAccess.qrCodeDataUrl);
    fireEvent.click(within(reopened).getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Open chat" }));
    await waitFor(() =>
      expect(mocks.show).toHaveBeenCalledWith(expect.objectContaining({ snapshot: runningSnapshot })),
    );
    expect(mocks.launch).toHaveBeenCalledTimes(1);
    expect(mocks.close).not.toHaveBeenCalled();
  });
  it("allows cancelling an end without interrupting the phone", async () => {
    mocks.status.mockResolvedValue({ state: "running" });
    page();
    await screen.findByRole("heading", { name: "Currently chatting: Evening" });
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    const confirmation = screen.getByRole("dialog", { name: "End chat" });
    expect(within(confirmation).getByText(/disconnects your phone.*history is kept/)).toBeVisible();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Cancel" }));
    expect(mocks.close).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Show QR code" })).toBeEnabled();
  });
  it("waits for ending, prevents duplicate stops, preserves history and permits the next mobile launch", async () => {
    mocks.status.mockResolvedValue({ state: "running" });
    let finish!: (value: unknown) => void;
    mocks.close.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { onCreate } = page();
    await screen.findByRole("heading", { name: "Currently chatting: Evening" });
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    const confirmation = screen.getByRole("dialog", { name: "End chat" });
    const confirm = within(confirmation).getByRole("button", { name: "End chat" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(mocks.close).toHaveBeenCalledTimes(1));
    expect(within(confirmation).getByRole("button", { name: "Ending…" })).toBeDisabled();
    expect(within(confirmation).getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "New chat" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Continue chat" })).toBeDisabled();
    mocks.status.mockResolvedValue({ state: "idle" });
    await act(async () => finish({ chatProcessRunning: false, chatRuntimeClosing: false }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Current chat" })).not.toBeInTheDocument());
    expect(screen.getByText("Good night")).toBeVisible();
    expect(mocks.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(onCreate).toHaveBeenCalledOnce();
    mocks.launch.mockImplementationOnce(async () => {
      mocks.status.mockResolvedValue({ state: "running" });
      mocks.current.mockResolvedValue({ ...entry, title: "Morning" });
      mocks.snapshot.mockResolvedValue({ ...runningSnapshot, sessionId: "runtime-two" });
      return { ...runningSnapshot, sessionId: "runtime-two" };
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Connect phone" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue chat" }));
    expect(await screen.findByRole("dialog", { name: "Mobile access is ready" })).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Currently chatting: Morning" })).toBeVisible();
  });
  it("keeps the confirmation and offers retry after a failed stop", async () => {
    mocks.status.mockResolvedValue({ state: "running" });
    mocks.close.mockRejectedValueOnce(new Error("Could not stop chat"));
    page();
    await screen.findByRole("heading", { name: "Currently chatting: Evening" });
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    const confirmation = screen.getByRole("dialog", { name: "End chat" });
    fireEvent.click(within(confirmation).getByRole("button", { name: "End chat" }));
    expect(await within(confirmation).findByRole("alert")).toHaveTextContent("Could not stop chat");
    expect(screen.getByRole("button", { name: "Continue chat" })).toBeDisabled();
    mocks.close.mockImplementationOnce(async () => {
      mocks.status.mockResolvedValue({ state: "idle" });
      return { chatProcessRunning: false };
    });
    fireEvent.click(within(confirmation).getByRole("button", { name: "Retry ending chat" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue chat" })).toBeEnabled());
    expect(mocks.close).toHaveBeenCalledTimes(2);
  });
  it("does not end a different session that appeared during confirmation", async () => {
    mocks.status.mockResolvedValue({ state: "running" });
    page();
    await screen.findByRole("heading", { name: "Currently chatting: Evening" });
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    mocks.snapshot.mockResolvedValue({ ...runningSnapshot, sessionId: "different" });
    const confirmation = screen.getByRole("dialog", { name: "End chat" });
    fireEvent.click(within(confirmation).getByRole("button", { name: "End chat" }));
    expect(await within(confirmation).findByRole("alert")).toHaveTextContent("The current chat has changed");
    expect(mocks.close).not.toHaveBeenCalled();
  });
  it("hides phone controls for a local chat and removes the banner when ended elsewhere", async () => {
    mocks.status.mockResolvedValue({ state: "running" });
    mocks.snapshot.mockResolvedValue({ ...runningSnapshot, mobileAccess: undefined });
    const { client } = page();
    await screen.findByRole("heading", { name: "Currently chatting: Evening" });
    expect(screen.queryByRole("button", { name: "Show QR code" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    expect(screen.getByText("Chat history is kept so you can continue later.")).toBeVisible();
    mocks.status.mockResolvedValue({ state: "idle" });
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["chat", "runtime-status"] });
    });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Current chat" })).not.toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New chat" })).toBeEnabled();
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
