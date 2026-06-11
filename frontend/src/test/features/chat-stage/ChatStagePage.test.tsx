import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatStagePage } from "../../../features/chat-stage/ChatStagePage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { ChatCommand, ChatHistoryEntry, ChatSnapshot, ChatStageEvent } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mocks = {
  closeChat: vi.fn(),
  getChatHistory: vi.fn(),
  getChatSnapshot: vi.fn(),
  getChatTheme: vi.fn(),
  sendChatCommand: vi.fn(),
  subscribeChatEvents: vi.fn(),
};

vi.mock("../../../entities/chat/repository", () => ({
  closeChat: () => mocks.closeChat(),
  getChatHistory: () => mocks.getChatHistory(),
  getChatSnapshot: () => mocks.getChatSnapshot(),
  getChatTheme: () => mocks.getChatTheme(),
  sendChatCommand: (command: ChatCommand) => mocks.sendChatCommand(command),
  subscribeChatEvents: (listener: (event: ChatStageEvent) => void) => mocks.subscribeChatEvents(listener),
}));

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
}));

const chatWindowMocks = vi.hoisted(() => ({
  closeChatSurface: vi.fn(),
}));

const desktopApiMocks = vi.hoisted(() => ({
  closeDesktopWindow: vi.fn(),
  isTauriDesktop: vi.fn(),
  minimizeDesktopWindow: vi.fn(),
  setDesktopWindowClickThrough: vi.fn(),
  startDesktopWindowDrag: vi.fn(),
  startDesktopWindowResize: vi.fn(),
  toggleMaximizeDesktopWindow: vi.fn(),
}));

vi.mock("../../../shared/desktop/chatWindow", () => ({
  closeChatSurface: (options: unknown) => chatWindowMocks.closeChatSurface(options),
}));

vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/desktop/desktopApi")>();
  return {
    ...actual,
    closeDesktopWindow: () => desktopApiMocks.closeDesktopWindow(),
    isTauriDesktop: () => desktopApiMocks.isTauriDesktop(),
    minimizeDesktopWindow: () => desktopApiMocks.minimizeDesktopWindow(),
    setDesktopWindowClickThrough: (ignore: boolean) => desktopApiMocks.setDesktopWindowClickThrough(ignore),
    startDesktopWindowDrag: () => desktopApiMocks.startDesktopWindowDrag(),
    startDesktopWindowResize: (direction: string) => desktopApiMocks.startDesktopWindowResize(direction),
    toggleMaximizeDesktopWindow: () => desktopApiMocks.toggleMaximizeDesktopWindow(),
  };
});

function snapshot(overrides: Partial<ChatSnapshot> = {}): ChatSnapshot {
  return {
    backgroundPath: "asset://school.png",
    characterName: "Mio",
    dialogText: "Ready",
    historyEntries: [
      { id: "history-0", role: "assistant", text: "Mio: Ready" },
      { id: "history-1", revertUserIndex: 0, role: "user", text: "你: hello" },
    ],
    historyPath: "D:/history/session.json",
    inputDraft: "",
    numericInfo: "idle / 2",
    options: ["Take the shortcut"],
    sprites: [{ id: "mio", label: "Mio", path: "asset://mio.png" }],
    status: "idle",
    voiceLanguage: "ja",
    ...overrides,
  };
}

function renderPage(initialEntries = ["/"]) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={initialEntries}>
        <I18nProvider language="en">
          <ChatStagePage />
        </I18nProvider>
      </MemoryRouter>
    </ToastProvider>,
  );
}

async function openToolbarMenu() {
  fireEvent.click(await screen.findByRole("button", { name: "Chat tools" }));
}

describe("ChatStagePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    mocks.closeChat.mockResolvedValue(snapshot());
    chatWindowMocks.closeChatSurface.mockResolvedValue(undefined);
    desktopApiMocks.closeDesktopWindow.mockResolvedValue(undefined);
    mocks.getChatTheme.mockResolvedValue({});
    mocks.getChatSnapshot.mockResolvedValue(snapshot());
    mocks.getChatHistory.mockResolvedValue(snapshot().historyEntries as ChatHistoryEntry[]);
    desktopApiMocks.isTauriDesktop.mockReturnValue(false);
    desktopApiMocks.minimizeDesktopWindow.mockResolvedValue(undefined);
    desktopApiMocks.setDesktopWindowClickThrough.mockResolvedValue(undefined);
    mocks.sendChatCommand.mockImplementation(async (command: ChatCommand) =>
      snapshot({
        dialogText: command.type,
        inputDraft: "",
        options: [],
      }),
    );
    desktopApiMocks.startDesktopWindowDrag.mockResolvedValue(undefined);
    desktopApiMocks.startDesktopWindowResize.mockResolvedValue(undefined);
    mocks.subscribeChatEvents.mockReturnValue(vi.fn());
    desktopApiMocks.toggleMaximizeDesktopWindow.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends option selections and typed dialogue through chat commands", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Take the shortcut" }));
    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "Take the shortcut",
        type: "submit-option",
      }),
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  hello  " } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "hello",
        type: "send-message",
      }),
    );
  });

  it("submits typed dialogue with Enter while preserving Shift+Enter for line breaks", async () => {
    renderPage();

    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: "  enter submit  " } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "enter submit",
        type: "send-message",
      }),
    );

    fireEvent.change(input, { target: { value: "draft line" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });

    expect(mocks.sendChatCommand).not.toHaveBeenCalledWith({
      payload: "draft line",
      type: "send-message",
    });
  });

  it("enables click-through transparent desktop space and custom resize handles", async () => {
    desktopApiMocks.isTauriDesktop.mockReturnValue(true);
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ backgroundPath: "" }));

    renderPage(["/chat-stage"]);

    await screen.findByText("Ready");
    const stage = document.querySelector(".chat-stage");
    expect(stage).toHaveAttribute("data-click-through", "true");
    expect(document.querySelector(".desktop-resize-handles")).not.toBeNull();

    fireEvent.pointerMove(stage!);
    await waitFor(() => expect(desktopApiMocks.setDesktopWindowClickThrough).toHaveBeenCalledWith(true));

    fireEvent.pointerMove(screen.getByRole("textbox"));
    await waitFor(() => expect(desktopApiMocks.setDesktopWindowClickThrough).toHaveBeenCalledWith(false));

    fireEvent.mouseDown(document.querySelector(".desktop-resize-handle--se")!, { button: 0 });
    expect(desktopApiMocks.startDesktopWindowResize).toHaveBeenCalledWith("SouthEast");
  });

  it("keeps the stage transparent when the snapshot has no background path", async () => {
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ backgroundPath: "" }));

    renderPage();

    await screen.findByText("Ready");
    expect(document.querySelector(".chat-stage")).toHaveAttribute("data-background", "transparent");
    expect(document.querySelector(".chat-stage__background")).toHaveAttribute("data-transparent", "true");
    expect(document.querySelector(".chat-stage__fallback")).toBeNull();
    expect(document.body.dataset.chatStageTransparent).toBe("true");
  });

  it("requires confirmation before clearing chat history", async () => {
    renderPage();

    await openToolbarMenu();
    fireEvent.click(await screen.findByRole("button", { name: "Clear history" }));
    expect(mocks.sendChatCommand).not.toHaveBeenCalledWith({ type: "clear-history" });

    const dialog = screen.getByRole("dialog", { name: "Clear history" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear" }));

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "clear-history" }));
  });

  it("switches the toolbar ASR button to resume when the stage is paused", async () => {
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ status: "paused" }));

    renderPage();

    await openToolbarMenu();
    fireEvent.click(await screen.findByRole("button", { name: "Resume ASR" }));

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "resume-asr" }));
  });

  it("sends change-voice-language from the toolbar selector", async () => {
    renderPage();

    expect(await screen.findByText("Snapshot")).toBeInTheDocument();
    await openToolbarMenu();

    fireEvent.click(await screen.findByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "English" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "en",
        type: "change-voice-language",
      }),
    );
  });

  it("loads runtime history into the dialog and sends revert-history after confirmation", async () => {
    renderPage();

    await openToolbarMenu();
    fireEvent.click(await screen.findByRole("button", { name: "Open history" }));

    await waitFor(() => expect(mocks.getChatHistory).toHaveBeenCalledTimes(1));
    const dialog = await screen.findByRole("dialog", { name: "Conversation history" });
    expect(within(dialog).getByText("Mio: Ready")).toBeInTheDocument();
    expect(within(dialog).getByText("你: hello")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Revert to previous turn" }));

    const confirm = await screen.findByRole("dialog", { name: "Revert history" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Revert" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: 0,
        type: "revert-history",
      }),
    );
  });

  it("toggles layers from incoming stage events", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });

    renderPage();
    await screen.findByText("Ready");

    act(() => {
      listener?.({
        seq: 1,
        state: "reconnecting",
        transport: "websocket",
        ts: Date.now(),
        type: "transport.state",
        v: 1,
      });
    });
    expect(await screen.findByText("Reconnecting")).toBeInTheDocument();

    act(() => {
      listener?.({
        durationSeconds: 3,
        seq: 2,
        text: "Loading scene",
        ts: Date.now(),
        type: "busy.show",
        v: 1,
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Loading scene");

    act(() => {
      listener?.({
        reason: "Session closed",
        seq: 3,
        ts: Date.now(),
        type: "session.closed",
        v: 1,
      });
    });
    expect(await screen.findByText("Session closed")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    act(() => {
      listener?.({
        seq: 4,
        ts: Date.now(),
        type: "cg.show",
        url: "asset://cg.png",
        v: 1,
      });
    });
    expect(document.querySelector(".chat-stage__cg img")).toHaveAttribute("src", "asset://cg.png");
    expect(document.querySelector(".sprite-layer")).toHaveAttribute("hidden");
  });

  it("plays dialog.end events through the frontend typewriter and lets users skip", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });

    renderPage();
    await screen.findByText("Ready");
    vi.useFakeTimers();

    act(() => {
      listener?.({
        color: "#fff",
        fullHtml: "<p><b style='color:#fff;'>Mio</b>：Hello<br>world</p>",
        isSystem: false,
        seq: 4,
        speaker: "Mio",
        ts: Date.now(),
        type: "dialog.end",
        v: 1,
      });
    });

    const dialogText = document.querySelector(".dialog-layer__text") as HTMLElement;
    expect(dialogText.textContent).toBe("");

    act(() => {
      vi.advanceTimersByTime(75);
    });
    expect(dialogText.textContent).toBe("H");

    fireEvent.click(dialogText);
    expect(dialogText.textContent).toBe("Helloworld");
    expect(screen.getAllByText("Mio")[0]).toBeInTheDocument();
    expect(mocks.sendChatCommand).not.toHaveBeenCalled();
  });

  it("sends dialog-advance when users click a fully rendered dialog line", async () => {
    renderPage();

    const dialogText = await screen.findByText("Ready");
    fireEvent.click(dialogText);

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "dialog-advance" }));
  });

  it("ignores stale dialog.end events after a newer snapshot has already hydrated", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        dialogText: "Recovered",
        eventSeq: 10,
      }),
    );

    renderPage();
    await screen.findByText("Recovered");

    act(() => {
      listener?.({
        color: "#fff",
        fullHtml: "<p><b style='color:#fff;'>Mio</b>：Old line</p>",
        isSystem: false,
        seq: 4,
        speaker: "Mio",
        ts: Date.now(),
        type: "dialog.end",
        v: 1,
      });
    });

    const dialogText = document.querySelector(".dialog-layer__text") as HTMLElement;
    expect(dialogText.textContent).toBe("Recovered");
  });

  it("does not render a stale speaker name when snapshot hydration restores a system dialog", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        characterName: "",
        dialogText: "Recovered system line",
        historyEntries: [],
        options: [],
      }),
    );
    mocks.getChatHistory.mockResolvedValue([]);

    renderPage();

    await screen.findByText("Recovered system line");
    expect(document.querySelector(".dialog-layer__name")).toBeNull();
  });

  it("reopens the input layer when a command result clears closed-session markers", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        notificationText: "聊天会话已结束。",
        options: [],
        sessionClosedReason: "聊天会话已结束。",
        status: "paused",
      }),
    );
    mocks.sendChatCommand.mockResolvedValue(
      snapshot({
        notificationText: "",
        options: [],
        sessionClosedReason: "",
        status: "listening",
      }),
    );

    renderPage();

    await screen.findByText("聊天会话已结束。");
    expect(screen.queryByPlaceholderText("Enter dialogue")).not.toBeInTheDocument();

    await openToolbarMenu();
    fireEvent.click(screen.getByRole("button", { name: "Resume ASR" }));

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "resume-asr" }));
    await waitFor(() => expect(screen.getByPlaceholderText("Enter dialogue")).toBeInTheDocument());
    expect(screen.queryByText("聊天会话已结束。")).not.toBeInTheDocument();
  });

  it("closes the chat surface explicitly from the toolbar", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        runtimeMode: "react",
        sessionId: "session-1",
        wsUrl: "ws://127.0.0.1:8788/ws",
      }),
    );

    renderPage();
    await screen.findByText("Ready");
    await openToolbarMenu();
    fireEvent.click(screen.getByRole("button", { name: "Close chat" }));

    await waitFor(() => expect(chatWindowMocks.closeChatSurface).toHaveBeenCalledTimes(1));

    const [options] = chatWindowMocks.closeChatSurface.mock.calls[0] ?? [];
    expect(options).toEqual(
      expect.objectContaining({
        closeRuntime: expect.any(Function),
        navigate: expect.any(Function),
        snapshot: expect.objectContaining({
          runtimeMode: "react",
          sessionId: "session-1",
          wsUrl: "ws://127.0.0.1:8788/ws",
        }),
      }),
    );
  });

  it("renders dedicated window controls for the standalone desktop chat route", async () => {
    desktopApiMocks.isTauriDesktop.mockReturnValue(true);

    const { container } = renderPage(["/chat-stage"]);
    await screen.findByText("Ready");

    expect(screen.getByRole("button", { name: "Minimize" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Maximize" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close chat" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Minimize" }));
    fireEvent.click(screen.getByRole("button", { name: "Maximize" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.mouseDown(container.querySelector(".desktop-chat-controls__drag")!, { button: 0 });

    await waitFor(() => expect(desktopApiMocks.minimizeDesktopWindow).toHaveBeenCalledTimes(1));
    expect(desktopApiMocks.toggleMaximizeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApiMocks.closeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApiMocks.startDesktopWindowDrag).toHaveBeenCalledTimes(1);
    expect(chatWindowMocks.closeChatSurface).not.toHaveBeenCalled();
  });
});
