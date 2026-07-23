import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { CSSProperties } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatStagePage } from "../../../features/chat-stage/ChatStagePage";
import {
  chatStageRuntimeConfigVersion,
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
} from "../../../features/chat-stage/runtimeConfig";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type {
  ChatAttachmentInput,
  ChatCommand,
  ChatHistoryEntry,
  ChatSnapshot,
  ChatStageEvent,
} from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mocks = {
  browseFiles: vi.fn(),
  closeChat: vi.fn(),
  getAppConfig: vi.fn(),
  getChatHistory: vi.fn(),
  getChatSnapshot: vi.fn(),
  getChatTheme: vi.fn(),
  sendChatCommand: vi.fn(),
  subscribeChatEvents: vi.fn(),
  uploadChatAttachments: vi.fn(),
};

const themeContextMocks = vi.hoisted(() => ({
  optional: null as null | {
    resolved?: { typewriter: { cps: number } };
    style: CSSProperties;
  },
}));

vi.mock("../../../entities/chat/repository", () => ({
  closeChat: () => mocks.closeChat(),
  getChatHistory: () => mocks.getChatHistory(),
  getChatSnapshot: () => mocks.getChatSnapshot(),
  getChatTheme: () => mocks.getChatTheme(),
  sendChatCommand: (command: ChatCommand) => mocks.sendChatCommand(command),
  subscribeChatEvents: (listener: (event: ChatStageEvent) => void) => mocks.subscribeChatEvents(listener),
  uploadChatAttachments: (files: File[]) => mocks.uploadChatAttachments(files),
}));

vi.mock("../../../entities/config/repository", () => ({
  getAppConfig: () => mocks.getAppConfig(),
}));

vi.mock("../../../entities/files/repository", () => ({
  browseFiles: (options?: { path?: string; showHidden?: boolean }) => mocks.browseFiles(options),
}));

vi.mock("../../../features/chat-stage/theme/ChatThemeProvider", () => ({
  useOptionalChatTheme: () => themeContextMocks.optional,
}));

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
}));

const chatWindowMocks = vi.hoisted(() => ({
  closeChatSurface: vi.fn(),
}));

const desktopApiMocks = vi.hoisted(() => ({
  closeDesktopWindow: vi.fn(),
  getDesktopWindowCursorPosition: vi.fn(),
  isTauriDesktop: vi.fn(),
  minimizeDesktopWindow: vi.fn(),
  setDesktopWindowAlwaysOnTop: vi.fn(),
  setDesktopWindowClickThrough: vi.fn(),
  startDesktopWindowDrag: vi.fn(),
  startDesktopWindowResize: vi.fn(),
  toggleMaximizeDesktopWindow: vi.fn(),
}));

const userHistoryCreatedAt = new Date(2026, 0, 2, 3, 4).getTime();

vi.mock("../../../shared/desktop/chatWindow", () => ({
  closeChatSurface: (options: unknown) => chatWindowMocks.closeChatSurface(options),
}));

vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/desktop/desktopApi")>();
  return {
    ...actual,
    closeDesktopWindow: () => desktopApiMocks.closeDesktopWindow(),
    getDesktopWindowCursorPosition: () => desktopApiMocks.getDesktopWindowCursorPosition(),
    isTauriDesktop: () => desktopApiMocks.isTauriDesktop(),
    minimizeDesktopWindow: () => desktopApiMocks.minimizeDesktopWindow(),
    setDesktopWindowAlwaysOnTop: (alwaysOnTop: boolean) => desktopApiMocks.setDesktopWindowAlwaysOnTop(alwaysOnTop),
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
    experimentalFeatures: {
      conversationTree: true,
      forkHistory: true,
    },
    historyEntries: [
      { id: "history-0", role: "assistant", text: "Mio: Ready" },
      {
        createdAt: userHistoryCreatedAt,
        id: "history-1",
        revertUserIndex: 0,
        role: "user",
        text: "你: hello",
      },
    ],
    historyPath: "D:/history/session.json",
    inputDraft: "",
    numericInfo: "idle / 2",
    options: [],
    sprites: [{ id: "mio", label: "Mio", path: "asset://mio.png" }],
    status: "idle",
    userDisplayName: "Aoi",
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

function chooseCustomSelectOption(root: HTMLElement, name: string, option: string) {
  fireEvent.click(within(root).getByRole("combobox", { name }));
  fireEvent.click(screen.getByRole("option", { name: option }));
}

describe("ChatStagePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
    themeContextMocks.optional = null;
    mocks.closeChat.mockResolvedValue(snapshot());
    mocks.getAppConfig.mockResolvedValue({
      api_config: {
        asr_extra_configs: {
          vosk: { model_path: "D:/models/vosk" },
        },
      },
    });
    mocks.browseFiles.mockResolvedValue({
      cwd: "D:/models/vosk",
      entries: [
        { kind: "directory", name: "am", path: "D:/models/vosk/am" },
        { kind: "directory", name: "conf", path: "D:/models/vosk/conf" },
        { kind: "directory", name: "graph", path: "D:/models/vosk/graph" },
      ],
      roots: [],
    });
    chatWindowMocks.closeChatSurface.mockResolvedValue(undefined);
    desktopApiMocks.closeDesktopWindow.mockResolvedValue(undefined);
    mocks.getChatTheme.mockResolvedValue({});
    mocks.getChatSnapshot.mockResolvedValue(snapshot());
    mocks.getChatHistory.mockResolvedValue(snapshot().historyEntries as ChatHistoryEntry[]);
    desktopApiMocks.isTauriDesktop.mockReturnValue(false);
    desktopApiMocks.getDesktopWindowCursorPosition.mockResolvedValue({ x: 0, y: 0 });
    desktopApiMocks.minimizeDesktopWindow.mockResolvedValue(undefined);
    desktopApiMocks.setDesktopWindowAlwaysOnTop.mockResolvedValue(undefined);
    desktopApiMocks.setDesktopWindowClickThrough.mockResolvedValue(undefined);
    mocks.sendChatCommand.mockImplementation(async (command: ChatCommand) =>
      snapshot({
        dialogText: command.type,
        inputDraft: "",
        options: [],
        ...(command.type === "update-turn-options"
          ? { turnOptions: command.payload as ChatSnapshot["turnOptions"] }
          : {}),
      }),
    );
    mocks.uploadChatAttachments.mockReset();
    mocks.uploadChatAttachments.mockResolvedValue({ attachments: [] });
    desktopApiMocks.startDesktopWindowDrag.mockResolvedValue(undefined);
    desktopApiMocks.startDesktopWindowResize.mockResolvedValue(undefined);
    mocks.subscribeChatEvents.mockReturnValue(vi.fn());
    desktopApiMocks.toggleMaximizeDesktopWindow.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends option selections through chat commands", async () => {
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ options: ["Take the shortcut"] }));
    renderPage();

    const option = await screen.findByRole("button", { name: "Take the shortcut" });
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    expect(option.closest(".dialog-stack")).not.toBeNull();
    expect(document.querySelector('.options-layer > [data-theme-frame="chat-dialog"]')).not.toBeInTheDocument();
    expect(document.querySelector('.options-layer__item > [data-theme-frame="chat-option"]')).toBeInTheDocument();
    expect(option.closest(".options-layer__scroll")).not.toBeNull();
    fireEvent.click(option);
    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "Take the shortcut",
        type: "submit-option",
      }),
    );
  });

  it("focuses the first option and submits the focused choice with Enter", async () => {
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ options: ["Take the shortcut", "Stay on the road"] }));
    renderPage();

    const firstOption = await screen.findByRole("button", { name: "Take the shortcut" });
    expect(screen.getByRole("list", { name: "Dialogue choices" })).toContainElement(firstOption);
    expect(firstOption).toHaveFocus();

    fireEvent.keyDown(firstOption, { key: "Enter" });

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "Take the shortcut",
        type: "submit-option",
      }),
    );
  });

  it("exposes notifications as status updates and softens them over sprites", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        characterName: "",
        dialogText: "",
        notificationText: "Session paused",
      }),
    );
    renderPage();

    const notification = await screen.findByRole("status");
    expect(notification).toHaveClass("chat-stage__notification");
    expect(notification).toHaveAttribute("data-sprites-visible", "true");
    expect(notification).toHaveTextContent("Session paused");
  });

  it("opens interrupt and stacking switches from the existing hover input toolbar", async () => {
    themeContextMocks.optional = {
      style: {
        "--chat-dialog-toolbar-placement": "input",
        "--chat-dialog-toolbar-reveal": "hover",
      } as CSSProperties,
    };
    renderPage();

    const input = await screen.findByRole("textbox");
    expect(document.querySelector(".input-layer__turn-bar")).toBeNull();
    const toolbarLayer = document.querySelector(".dialog-toolbar-layer") as HTMLElement;
    expect(toolbarLayer).toHaveAttribute("data-placement", "input");
    expect(toolbarLayer).toHaveAttribute("data-reveal", "hover");
    const toolbar = within(toolbarLayer).getByRole("toolbar", { name: "Chat stage actions" });
    const settingsButton = within(toolbar).getByRole("button", { name: "Chat settings" });
    expect(screen.queryByRole("dialog", { name: "Chat settings" })).not.toBeInTheDocument();

    fireEvent.click(settingsButton);
    const settings = screen.getByRole("dialog", { name: "Chat settings" });
    const stackSwitch = within(settings).getByRole("checkbox", { name: "Stack consecutive messages" });
    expect(stackSwitch).not.toBeChecked();
    expect(within(settings).getByRole("checkbox", { name: "Allow new messages to interrupt replies" })).toBeChecked();

    fireEvent.change(input, { target: { value: "keep this draft" } });
    fireEvent.click(stackSwitch);

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: { batchEnabled: true, batchIdleSeconds: 5, interruptEnabled: true },
        type: "update-turn-options",
      }),
    );
    await waitFor(() => expect(stackSwitch).toBeChecked());
    expect(input).toHaveValue("keep this draft");
  });

  it("shows pending stack state and keeps input enabled only when interruption is allowed", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        status: "generating",
        turnOptions: { batchEnabled: true, batchIdleSeconds: 5, interruptEnabled: true },
        turnState: {
          enabled: true,
          pendingCount: 2,
          remainingSeconds: 4,
          scheduled: true,
          typing: false,
        },
      }),
    );

    const { unmount } = renderPage();

    expect(await screen.findByRole("textbox")).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Chat settings" }));
    expect(screen.getByRole("status")).toHaveTextContent(/2 queued.*4s/);
    unmount();

    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        status: "generating",
        turnOptions: { batchEnabled: false, batchIdleSeconds: 5, interruptEnabled: false },
      }),
    );
    renderPage();
    expect(await screen.findByRole("textbox")).toBeDisabled();
  });

  it("anchors decorative frames to the main chat surfaces", async () => {
    renderPage();

    await screen.findByText("Ready");
    expect(document.querySelector('.dialog-layer > [data-theme-frame="chat-dialog"]')).toBeInTheDocument();
    expect(document.querySelector('.dialog-layer__name > [data-theme-frame="chat-name"]')).toBeInTheDocument();
    expect(document.querySelector('.input-layer > [data-theme-frame="chat-input"]')).toBeInTheDocument();
    expect(document.querySelector('.top-stage-tools > [data-theme-frame="chat-toolbar"]')).toBeInTheDocument();
    expect(
      document.querySelector('.dialog-stage-controls__surface > [data-theme-frame="chat-toolbar"]'),
    ).toBeInTheDocument();
  });

  it("suppresses context menus inside the chat stage", async () => {
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ options: ["Take the shortcut"] }));
    renderPage();

    await screen.findByRole("button", { name: "Take the shortcut" });
    const stage = document.querySelector(".chat-stage") as HTMLElement;
    expect(fireEvent.contextMenu(stage)).toBe(false);
    expect(fireEvent.contextMenu(screen.getByRole("button", { name: "Take the shortcut" }))).toBe(false);
  });

  it("submits typed dialogue with Enter while preserving Shift+Enter for line breaks", async () => {
    renderPage();

    const input = await screen.findByRole("textbox");
    expect(input.tagName).toBe("TEXTAREA");
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

  it.each([
    { inputTag: "TEXTAREA", layout: "default" as const },
    { inputTag: "INPUT", layout: "pill" as const },
  ])("submits the current $layout fragment before flushing a batch with Ctrl+Enter", async ({ inputTag, layout }) => {
    if (layout === "pill") {
      themeContextMocks.optional = {
        resolved: { typewriter: { cps: 40 } },
        style: { "--chat-input-layout": "pill" } as CSSProperties,
      };
    }
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({ turnOptions: { batchEnabled: true, batchIdleSeconds: 5, interruptEnabled: true } }),
    );
    renderPage();

    const input = await screen.findByRole("textbox");
    expect(input.tagName).toBe(inputTag);
    fireEvent.change(input, { target: { value: "flush this fragment" } });
    mocks.sendChatCommand.mockClear();
    fireEvent.keyDown(input, { ctrlKey: true, key: "Enter" });

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledTimes(2));
    expect(mocks.sendChatCommand).toHaveBeenNthCalledWith(1, {
      payload: "flush this fragment",
      type: "send-message",
    });
    expect(mocks.sendChatCommand).toHaveBeenNthCalledWith(2, { type: "flush-input-batch" });
  });

  it("clears the draft and shows the user message before the command response arrives", async () => {
    let resolveCommand!: (snapshot: ChatSnapshot) => void;
    mocks.sendChatCommand.mockReturnValueOnce(
      new Promise<ChatSnapshot>((resolve) => {
        resolveCommand = resolve;
      }),
    );
    renderPage();

    await screen.findByText("Ready");
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "  hello from Aoi  " } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(input).toHaveValue("");
    expect(screen.getByText("Aoi")).toBeInTheDocument();
    expect(screen.getByText("hello from Aoi")).toBeInTheDocument();
    expect(mocks.sendChatCommand).toHaveBeenCalledTimes(1);
    expect(mocks.sendChatCommand).toHaveBeenCalledWith({
      payload: "hello from Aoi",
      type: "send-message",
    });

    await act(async () => {
      resolveCommand(snapshot({ characterName: "Aoi", dialogText: "hello from Aoi", inputDraft: "" }));
    });
    expect(screen.getByText("hello from Aoi")).toBeInTheDocument();
  });

  it("keeps the submitted user message when a stale stream snapshot arrives", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ eventSeq: 3 }));
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    renderPage();

    await screen.findByText("Ready");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "stay visible" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByText("stay visible")).toBeInTheDocument();

    act(() => {
      listener?.({
        seq: 3,
        snapshot: snapshot({ characterName: "Mio", dialogText: "old reply", eventSeq: 3 }),
        ts: Date.now(),
        type: "snapshot",
        v: 1,
      });
    });

    expect(document.querySelector(".dialog-layer__name")).toHaveTextContent("Aoi");
    expect(screen.getByText("stay visible")).toBeInTheDocument();
    expect(screen.queryByText("old reply")).not.toBeInTheDocument();
  });

  it("remounts only the sprite image when an expression changes so the switch animation replays", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({ sprites: [{ id: "Mio", label: "Mio", path: "asset://mio.png", slot: 0 }] }),
    );
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    const { container } = renderPage();

    await screen.findByText("Ready");
    const originalFigure = container.querySelector(".sprite-layer__figure");
    const originalImage = container.querySelector(".sprite-layer__image");

    act(() => {
      listener?.({
        characterName: "Mio",
        scale: 1,
        seq: 1,
        slot: 0,
        ts: 1,
        type: "sprite.show",
        url: "asset://mio-happy.png",
        v: 1,
      });
    });

    const nextFigure = container.querySelector(".sprite-layer__figure");
    const nextImage = container.querySelector(".sprite-layer__image");
    expect(nextFigure).toBe(originalFigure);
    expect(nextFigure).toHaveAttribute("data-slot", "0");
    expect(nextImage).not.toBe(originalImage);
    expect(nextImage).toHaveAttribute("src", "asset://mio-happy.png");
  });

  it("switches the rendered background and looping BGM from stream events", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        backgroundPath: "asset://day-room.png",
        bgmPath: "asset://day-theme.mp3",
        eventSeq: 0,
      }),
    );
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    const { container } = renderPage();

    await screen.findByText("Ready");
    expect(container.querySelector(".chat-stage__background img")).toHaveAttribute("src", "asset://day-room.png");
    expect(container.querySelector("audio[data-chat-stage-bgm]")).toHaveAttribute("src", "asset://day-theme.mp3");
    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));

    act(() => {
      listener?.({
        seq: 1,
        ts: 1,
        type: "background.change",
        url: "asset://night-room.png",
        v: 1,
      });
      listener?.({
        seq: 2,
        ts: 2,
        type: "bgm.change",
        url: "asset://night-theme.mp3",
        v: 1,
      });
    });

    expect(container.querySelector(".chat-stage__background img")).toHaveAttribute("src", "asset://night-room.png");
    expect(container.querySelector("audio[data-chat-stage-bgm]")).toHaveAttribute("src", "asset://night-theme.mp3");
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(pause).toHaveBeenCalledTimes(1);

    act(() => {
      listener?.({ seq: 3, ts: 3, type: "bgm.change", url: "", v: 1 });
    });

    expect(container.querySelector("audio[data-chat-stage-bgm]")).not.toBeInTheDocument();
    expect(pause).toHaveBeenCalledTimes(2);
    play.mockRestore();
    pause.mockRestore();
  });

  it("reveals the native stat layer only after the first stats event", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ eventSeq: 0, stats: [] }));
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    renderPage();

    await screen.findByText("Ready");
    expect(screen.queryByRole("status", { name: "Character stats" })).not.toBeInTheDocument();
    expect(document.querySelector(".chat-stage")).toHaveAttribute("data-stat-visible", "false");

    act(() => {
      listener?.({
        seq: 1,
        stats: [
          { icon: "heart", label: "HP", max: 100, value: 72 },
          { icon: "coins", label: "Gold", value: 320 },
        ],
        ts: 1,
        type: "stats.update",
        v: 1,
      });
    });

    const statLayer = screen.getByRole("status", { name: "Character stats" });
    expect(statLayer).toHaveTextContent("HP72 / 100");
    expect(statLayer).toHaveTextContent("Gold320");
    expect(statLayer.querySelector('[data-icon="heart"] .lucide-heart')).not.toBeNull();
    expect(screen.getByRole("progressbar", { name: "HP" })).toHaveAttribute("value", "72");
    expect(screen.getByRole("progressbar", { name: "HP" })).toHaveAttribute("max", "100");
    expect(document.querySelector(".chat-stage")).toHaveAttribute("data-stat-visible", "true");

    act(() => {
      listener?.({
        color: "#fff",
        fullHtml: "<p>Stats remain visible</p>",
        isSystem: false,
        seq: 2,
        speaker: "Mio",
        ts: 2,
        type: "dialog.end",
        v: 1,
      });
    });
    expect(screen.getByRole("status", { name: "Character stats" })).toBeInTheDocument();
  });

  it("shows a selected option as the user message before the command response arrives", async () => {
    let resolveCommand!: (snapshot: ChatSnapshot) => void;
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ options: ["Take the shortcut"] }));
    mocks.sendChatCommand.mockReturnValueOnce(
      new Promise<ChatSnapshot>((resolve) => {
        resolveCommand = resolve;
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Take the shortcut" }));

    expect(screen.queryByRole("button", { name: "Take the shortcut" })).not.toBeInTheDocument();
    expect(screen.getByText("Aoi")).toBeInTheDocument();
    expect(screen.getByText("Take the shortcut")).toBeInTheDocument();
    expect(mocks.sendChatCommand).toHaveBeenCalledWith({
      payload: "Take the shortcut",
      type: "submit-option",
    });

    await act(async () => {
      resolveCommand(snapshot({ characterName: "Aoi", dialogText: "Take the shortcut", options: [] }));
    });
  });

  it("restores the options when an optimistic option command fails", async () => {
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ options: ["Take the shortcut"] }));
    mocks.sendChatCommand.mockRejectedValueOnce(new Error("option offline"));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Take the shortcut" }));

    expect(mocks.sendChatCommand).toHaveBeenCalledTimes(1);
    expect(mocks.sendChatCommand).toHaveBeenCalledWith({
      payload: "Take the shortcut",
      type: "submit-option",
    });
    expect(await screen.findByText("option offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Take the shortcut" })).toBeInTheDocument();
    expect(screen.queryByText("Aoi")).not.toBeInTheDocument();
    expect(document.querySelector(".top-stage-tools__state")).toHaveTextContent("idle");
  });

  it("does not let a late send acknowledgement overwrite the character reply", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    let resolveCommand!: (snapshot: ChatSnapshot) => void;
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ eventSeq: 3 }));
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    mocks.sendChatCommand.mockReturnValueOnce(
      new Promise<ChatSnapshot>((resolve) => {
        resolveCommand = resolve;
      }),
    );
    renderPage();

    await screen.findByText("Ready");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByText("Aoi")).toBeInTheDocument();

    act(() => {
      listener?.({
        color: "#fff",
        fullHtml: "<p>assistant reply</p>",
        isSystem: false,
        seq: 4,
        speaker: "Mio",
        ts: Date.now(),
        type: "dialog.end",
        v: 1,
      });
    });
    fireEvent.click(document.querySelector(".dialog-layer__text") as HTMLElement);
    expect(document.querySelector(".dialog-layer__name")).toHaveTextContent("Mio");
    expect(screen.getByText("assistant reply")).toBeInTheDocument();

    await act(async () => {
      resolveCommand(
        snapshot({ characterName: "Aoi", dialogText: "hello", eventSeq: 4, inputDraft: "", status: "generating" }),
      );
    });

    expect(document.querySelector(".dialog-layer__name")).toHaveTextContent("Mio");
    expect(screen.getByText("assistant reply")).toBeInTheDocument();
    expect(screen.queryByText("hello")).not.toBeInTheDocument();
  });

  it("restores the submitted draft when sending fails", async () => {
    mocks.sendChatCommand.mockRejectedValueOnce(new Error("offline"));
    renderPage();

    await screen.findByText("Ready");
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "retry me" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(input).toHaveValue("retry me"));
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(mocks.sendChatCommand).toHaveBeenCalledTimes(1);
    expect(mocks.sendChatCommand).toHaveBeenCalledWith({ payload: "retry me", type: "send-message" });
    expect(document.querySelector(".top-stage-tools__state")).toHaveTextContent("idle");
    expect(await screen.findByText("offline")).toBeInTheDocument();
  });

  it("enables click-through transparent desktop space and custom resize handles", async () => {
    desktopApiMocks.isTauriDesktop.mockReturnValue(true);
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ backgroundPath: "" }));
    desktopApiMocks.getDesktopWindowCursorPosition.mockResolvedValue({ x: 320, y: 180 });

    renderPage(["/chat-stage"]);

    await screen.findByText("Ready");
    const stage = document.querySelector(".chat-stage");
    expect(stage).toHaveAttribute("data-click-through", "true");
    expect(document.querySelector(".desktop-resize-handles")).not.toBeNull();

    await waitFor(() => expect(desktopApiMocks.setDesktopWindowClickThrough).toHaveBeenCalledWith(true));

    const input = screen.getByRole("textbox");
    const inputLayer = input.closest("[data-chat-stage-hitbox='true']") as HTMLElement;
    vi.spyOn(inputLayer, "getBoundingClientRect").mockReturnValue({
      bottom: 88,
      height: 64,
      left: 24,
      right: 480,
      toJSON: () => ({}),
      top: 24,
      width: 456,
      x: 24,
      y: 24,
    });
    desktopApiMocks.getDesktopWindowCursorPosition.mockResolvedValue({ x: 64, y: 48 });
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 60));
    });
    await waitFor(() => expect(desktopApiMocks.setDesktopWindowClickThrough).toHaveBeenCalledWith(false));

    fireEvent.pointerMove(input);
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

    await screen.findByText("Ready");
    fireEvent.click(await screen.findByRole("button", { name: "Open history" }));
    const historyDialog = await screen.findByRole("dialog", { name: "Conversation history" });
    fireEvent.click(within(historyDialog).getByRole("button", { name: "Clear history" }));
    expect(mocks.sendChatCommand).not.toHaveBeenCalledWith({ type: "clear-history" });

    const dialog = screen.getByRole("dialog", { name: "Clear history" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear" }));

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "clear-history" }));
  });

  it("switches the input ASR button to resume when the stage is paused", async () => {
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ status: "paused" }));

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Resume ASR" }));

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "resume-asr" }));
  });

  it("sends change-voice-language from the toolbar selector", async () => {
    renderPage();

    expect(await screen.findByText("Snapshot")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Chat appearance settings" }));

    const config = await screen.findByRole("dialog", { name: "Chat appearance settings" });
    fireEvent.click(within(config).getAllByRole("combobox")[0]);
    fireEvent.click(screen.getByRole("option", { name: "English" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "en",
        type: "change-voice-language",
      }),
    );
  });

  it("toggles token usage into the top overlay", async () => {
    renderPage();

    await screen.findByText("Ready");
    expect(screen.queryByText("idle / 2")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Token usage" }));

    const tokenLayer = document.querySelector(".token-usage-layer") as HTMLElement;
    expect(tokenLayer).not.toBeNull();
    expect(tokenLayer).toHaveTextContent(/TOKENS|Token usage/);
    expect(tokenLayer).toHaveTextContent("idle / 2");
    expect(document.querySelector(".chat-stage")).toHaveAttribute("data-token-visible", "true");

    fireEvent.click(screen.getByRole("button", { name: "Token usage" }));
    expect(document.querySelector(".token-usage-layer")).toBeNull();
    expect(document.querySelector(".chat-stage")).toHaveAttribute("data-token-visible", "false");
  });

  it("opens theme management from the top toolbar and disables transparent-window click-through", async () => {
    desktopApiMocks.isTauriDesktop.mockReturnValue(true);
    themeContextMocks.optional = { style: {} };
    mocks.getChatSnapshot.mockResolvedValue(snapshot({ backgroundPath: "" }));

    renderPage(["/chat-stage"]);

    await screen.findByText("Ready");
    const stage = document.querySelector(".chat-stage") as HTMLElement;
    expect(stage).toHaveAttribute("data-click-through", "true");

    fireEvent.click(screen.getByRole("button", { name: "Manage themes" }));

    const picker = await screen.findByRole("dialog", { name: "Chat themes" });
    expect(stage).toHaveAttribute("data-click-through", "false");

    fireEvent.click(within(picker).getByRole("button", { name: "Close" }));
    expect(stage).toHaveAttribute("data-click-through", "true");
  });

  it("renders core chat actions at the dialog bottom and supports locking the tray", async () => {
    renderPage();

    await screen.findByText("Ready");
    const dialog = document.querySelector(".dialog-layer") as HTMLElement;
    const dialogBody = dialog.querySelector(".dialog-layer__body") as HTMLElement;
    const dialogToolbar = within(dialog).getByRole("toolbar", { name: "Chat stage actions" });
    expect(dialogBody.compareDocumentPosition(dialogToolbar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.querySelector(".dialog-toolbar-layer")).toBeNull();

    const actionTray = document.querySelector(".dialog-stage-controls") as HTMLElement;
    expect(actionTray).not.toBeNull();
    expect(actionTray).toHaveAttribute("data-locked", "false");
    const actionBar = within(actionTray).getByRole("toolbar", { name: "Chat stage actions" });
    const lockButton = within(actionBar).getByRole("button", { name: "Lock chat actions" });
    expect(lockButton).toHaveTextContent("LOCK");
    expect(within(actionBar).getByRole("button", { name: "Open history" })).toHaveTextContent("HISTORY");
    expect(within(actionBar).getByRole("button", { name: "Open conversation tree" })).toHaveTextContent("TREE");
    expect(within(actionBar).getByRole("button", { name: "Retry reply" })).toHaveTextContent("RETRY");
    expect(within(actionBar).queryByRole("button", { name: "Skip" })).not.toBeInTheDocument();
    expect(within(actionBar).queryByRole("button", { name: "Copy history" })).not.toBeInTheDocument();
    expect(within(actionBar).queryByRole("button", { name: "Clear history" })).not.toBeInTheDocument();
    expect(within(actionBar).getByRole("button", { name: "Chat settings" })).toHaveTextContent("Chat settings");
    expect(within(actionBar).getByRole("button", { name: "Chat appearance settings" })).toHaveTextContent(
      "APPEARANCE SETTINGS",
    );
    expect(within(dialog).queryByRole("slider")).not.toBeInTheDocument();

    fireEvent.click(lockButton);
    expect(actionTray).toHaveAttribute("data-locked", "true");
    expect(within(actionBar).getByRole("button", { name: "Unlock chat actions" })).toHaveTextContent("UNLOCK");

    const topTools = document.querySelector(".top-stage-tools") as HTMLElement;
    const topControls = topTools.querySelector(".top-stage-tools__controls") as HTMLElement;
    expect(topTools).toHaveAttribute("tabindex", "0");
    expect(topTools).toHaveAttribute("aria-label", "Chat tools");
    topTools.focus();
    expect(topTools).toHaveFocus();
    expect(within(topControls).getByRole("button", { name: "Token usage" })).toBeInTheDocument();
    expect(within(topTools).queryByRole("button", { name: "Open history" })).not.toBeInTheDocument();
  });

  it("opens the conversation tree from the toolbar and switches branches", async () => {
    const conversationTree = {
      activeBranchId: "main",
      branches: [
        { id: "main", label: "Main", parentId: null },
        { forkedFromText: "hello", id: "branch-2", label: "Branch 2", parentId: "main" },
        { forkedFromText: "branch path", id: "branch-3", label: "Branch 3", parentId: "branch-2" },
      ],
    };
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        conversationTree,
      }),
    );
    mocks.sendChatCommand.mockImplementation(async (command: ChatCommand) =>
      snapshot({ conversationTree, dialogText: command.type, inputDraft: "", options: [] }),
    );

    renderPage();
    await screen.findByText("Ready");

    fireEvent.click(screen.getByRole("button", { name: "Open conversation tree" }));
    const dialog = await screen.findByRole("dialog", { name: "Conversation branches" });
    expect(within(dialog).getByText("Branch 2")).toBeInTheDocument();
    expect(within(dialog).getByText("Forked from: hello")).toBeInTheDocument();
    expect(within(dialog).getByText("Branch 3")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Collapse Branch 2" }));
    await waitFor(() => expect(within(dialog).queryByText("Branch 3")).not.toBeInTheDocument());

    fireEvent.click(within(dialog).getByRole("button", { name: "Expand Branch 2" }));
    await waitFor(() => expect(within(dialog).getByText("Branch 3")).toBeInTheDocument());

    const branch2Node = within(dialog).getByText("Branch 2").closest("article") as HTMLElement;
    fireEvent.click(within(branch2Node).getByRole("button", { name: "Rename Branch 2" }));
    fireEvent.change(within(branch2Node).getByRole("textbox", { name: "Branch name" }), {
      target: { value: "Side route" },
    });
    fireEvent.click(within(branch2Node).getByRole("button", { name: "Save branch name" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: { branchId: "branch-2", label: "Side route" },
        type: "rename-branch",
      }),
    );

    const refreshedBranch2Node = within(dialog).getByText("Branch 2").closest("article") as HTMLElement;
    fireEvent.click(within(refreshedBranch2Node).getByRole("button", { name: "Switch" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({ payload: "branch-2", type: "switch-branch" }),
    );
  });

  it("disables experimental conversation tree and hides fork controls unless enabled", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        experimentalFeatures: { conversationTree: false, forkHistory: false },
      }),
    );
    mocks.getChatHistory.mockResolvedValueOnce([
      {
        createdAt: userHistoryCreatedAt,
        id: "history-1",
        revertUserIndex: 0,
        role: "user",
        text: "你: hello",
      },
    ] satisfies ChatHistoryEntry[]);

    renderPage();
    await screen.findByText("Ready");

    expect(
      screen.getByRole("button", { name: "Conversation tree is experimental and disabled in settings" }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Open history" }));
    const dialog = await screen.findByRole("dialog", { name: "Conversation history" });
    expect(within(dialog).queryByRole("button", { name: "Fork" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Revert to previous turn" })).toBeInTheDocument();
  });

  it("uses opt-in theme placement for the detached dialog toolbar with start options", async () => {
    themeContextMocks.optional = {
      resolved: { typewriter: { cps: 40 } },
      style: {
        "--chat-dialog-toolbar-placement": "dialog-top",
        "--chat-dialog-toolbar-reveal": "hover",
        "--chat-name-hide-when-start-option": "true",
      } as CSSProperties,
    };
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        characterName: "七海千秋",
        options: ["开始"],
      }),
    );

    renderPage();

    await screen.findByRole("button", { name: "开始" });
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    expect(document.querySelector(".dialog-layer")).toBeNull();

    const toolbarLayer = document.querySelector(".dialog-toolbar-layer") as HTMLElement;
    expect(toolbarLayer).not.toBeNull();
    expect(toolbarLayer).toHaveAttribute("data-placement", "dialog-top");
    expect(toolbarLayer).toHaveAttribute("data-reveal", "hover");
    expect(within(toolbarLayer).getByRole("toolbar", { name: "Chat stage actions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始" })).toBeInTheDocument();
  });

  it("uses one click-to-toggle ASR microphone for the pill input theme", async () => {
    themeContextMocks.optional = {
      resolved: { typewriter: { cps: 40 } },
      style: { "--chat-input-layout": "pill" } as CSSProperties,
    };

    renderPage();

    await screen.findByText("Ready");
    fireEvent.click(screen.getByRole("button", { name: "Chat appearance settings" }));
    const config = await screen.findByRole("dialog", { name: "Chat appearance settings" });
    expect(config).toHaveClass("chat-stage-modal");
    expect(config.querySelector(".chat-stage-modal__header")).not.toBeNull();
    expect(within(config).queryByLabelText("Long press to talk")).not.toBeInTheDocument();
    fireEvent.click(within(config).getByRole("button", { name: "Close" }));

    const asrButtons = await screen.findAllByRole("button", { name: "Resume ASR" });
    expect(asrButtons).toHaveLength(1);
    fireEvent.click(asrButtons[0]);
    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "resume-asr" }));
  });

  it("uses a single-line pill input and scopes the plus panel to attachments", async () => {
    themeContextMocks.optional = {
      resolved: { typewriter: { cps: 40 } },
      style: {
        "--chat-input-layout": "pill",
        "--chat-send-background": "#123456",
        "--chat-send-border-color": "#abcdef",
        "--chat-send-border-radius": "14px",
        "--chat-send-box-shadow": "0 0 7px #abcdef",
        "--chat-send-color": "#fedcba",
        "--chat-toolbar-border-radius": "17px",
      } as CSSProperties,
    };

    renderPage();

    await screen.findByText("Ready");
    const input = screen.getByRole("textbox");
    expect(input.tagName).toBe("INPUT");
    const stage = document.querySelector(".chat-stage") as HTMLElement;
    const quickSubmit = document.querySelector(".input-layer__quick-submit") as HTMLElement;
    expect(stage.style.getPropertyValue("--chat-send-background")).toBe("#123456");
    expect(stage.style.getPropertyValue("--chat-toolbar-border-radius")).toBe("17px");
    expect(quickSubmit).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "More input actions" }));
    const panel = document.querySelector(".input-layer__panel") as HTMLElement;
    expect(panel).toHaveAttribute("data-open", "true");
    expect(within(panel).queryByRole("button", { name: "Start microphone" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Pause ASR" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Resume ASR" })).toHaveLength(1);
    expect(within(panel).getByRole("button", { name: "Image" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "File" })).toBeInTheDocument();

    fireEvent.pointerDown(document.body);
    await waitFor(() => expect(panel).toHaveAttribute("data-open", "false"));

    fireEvent.change(input, { target: { value: "  pill submit  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "pill submit",
        type: "send-message",
      }),
    );
  });

  it("selects image and file attachments from the default layout and sends a structured payload", async () => {
    mocks.browseFiles.mockImplementation(async (options?: { path?: string; showHidden?: boolean }) => {
      if (options?.path === "D:/models/vosk") {
        return {
          cwd: "D:/models/vosk",
          entries: [
            { kind: "directory", name: "am", path: "D:/models/vosk/am" },
            { kind: "directory", name: "conf", path: "D:/models/vosk/conf" },
            { kind: "directory", name: "graph", path: "D:/models/vosk/graph" },
          ],
          roots: [],
        };
      }
      return {
        cwd: "D:/attachments",
        entries: [
          { kind: "file", name: "scene.png", path: "D:/attachments/scene.png", size: 12 },
          { kind: "file", name: "notes.txt", path: "D:/attachments/notes.txt", size: 24 },
        ],
        roots: [],
      };
    });

    renderPage();
    await screen.findByText("Ready");

    fireEvent.click(screen.getByRole("button", { name: "Image" }));
    const imageDialog = await screen.findByRole("dialog", { name: "Attach images" });
    const imageEntry = await within(imageDialog).findByText("scene.png");
    expect(within(imageDialog).getByText("notes.txt").closest("tr")).not.toHaveClass("path-picker__row--selectable");
    fireEvent.click(imageEntry.closest("tr")!);
    fireEvent.click(within(imageDialog).getByRole("button", { name: "Select file" }));

    const imageAttachment = await screen.findByRole("button", { name: "Remove attachment scene.png" });
    expect(imageAttachment).toHaveAttribute("data-kind", "image");

    fireEvent.click(screen.getByRole("button", { name: "File" }));
    const fileDialog = await screen.findByRole("dialog", { name: "Attach files" });
    const fileEntry = await within(fileDialog).findByText("notes.txt");
    fireEvent.click(fileEntry.closest("tr")!);
    fireEvent.click(within(fileDialog).getByRole("button", { name: "Select file" }));

    const fileAttachment = await screen.findByRole("button", { name: "Remove attachment notes.txt" });
    expect(fileAttachment).toHaveAttribute("data-kind", "file");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Inspect these" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: {
          attachments: [
            { kind: "image", name: "scene.png", path: "D:/attachments/scene.png" },
            { kind: "file", name: "notes.txt", path: "D:/attachments/notes.txt" },
          ],
          text: "Inspect these",
        },
        type: "send-message",
      }),
    );
  });

  it("merges mixed browser drops in one atomic attachment update", async () => {
    const image = new File(["image"], "scene.png", { type: "image/png" });
    const documentFile = new File(["notes"], "notes.txt", { type: "text/plain" });
    mocks.uploadChatAttachments.mockResolvedValueOnce({
      attachments: [
        { kind: "image", name: "scene.png", path: "D:/staged/scene.png" },
        { kind: "file", name: "notes.txt", path: "D:/staged/notes.txt" },
      ],
    });

    renderPage();
    await screen.findByText("Ready");
    fireEvent.drop(document.querySelector(".input-layer")!, {
      dataTransfer: { files: [image, documentFile], types: ["Files"] },
    });

    expect(await screen.findByRole("button", { name: "Remove attachment scene.png" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Remove attachment notes.txt" })).toBeInTheDocument();
    expect(mocks.uploadChatAttachments).toHaveBeenCalledWith([image, documentFile]);
  });

  it("does not restore a removed attachment when an earlier drop finishes later", async () => {
    const first = new File(["first"], "first.txt", { type: "text/plain" });
    const second = new File(["second"], "second.png", { type: "image/png" });
    let resolveSecondUpload: (value: { attachments: ChatAttachmentInput[] }) => void = () => undefined;
    const secondUpload = new Promise<{ attachments: ChatAttachmentInput[] }>((resolve) => {
      resolveSecondUpload = resolve;
    });
    mocks.uploadChatAttachments
      .mockResolvedValueOnce({
        attachments: [{ kind: "file", name: "first.txt", path: "D:/staged/first.txt" }],
      })
      .mockReturnValueOnce(secondUpload);

    renderPage();
    await screen.findByText("Ready");
    const inputLayer = document.querySelector(".input-layer")!;
    fireEvent.drop(inputLayer, { dataTransfer: { files: [first], types: ["Files"] } });
    const removeFirst = await screen.findByRole("button", { name: "Remove attachment first.txt" });

    fireEvent.drop(inputLayer, { dataTransfer: { files: [second], types: ["Files"] } });
    fireEvent.click(removeFirst);
    expect(screen.queryByRole("button", { name: "Remove attachment first.txt" })).not.toBeInTheDocument();

    resolveSecondUpload({
      attachments: [{ kind: "image", name: "second.png", path: "D:/staged/second.png" }],
    });

    expect(await screen.findByRole("button", { name: "Remove attachment second.png" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove attachment first.txt" })).not.toBeInTheDocument();
  });

  it("lets the configured backend report ASR availability instead of probing Vosk in the frontend", async () => {
    mocks.browseFiles.mockResolvedValueOnce({
      cwd: "D:/models/vosk",
      entries: [],
      roots: [],
    });
    themeContextMocks.optional = {
      resolved: { typewriter: { cps: 40 } },
      style: { "--chat-input-layout": "pill" } as CSSProperties,
    };

    renderPage();

    await screen.findByText("Ready");
    expect(mocks.browseFiles).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Resume ASR" }));
    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "resume-asr" }));
  });

  it("keeps the current dialog visible after copying history", async () => {
    mocks.sendChatCommand.mockResolvedValue(
      snapshot({
        dialogText: "",
        inputDraft: "",
        options: [],
      }),
    );

    renderPage();

    await screen.findByText("Ready");
    fireEvent.click(screen.getByRole("button", { name: "Open history" }));
    const historyDialog = await screen.findByRole("dialog", { name: "Conversation history" });
    fireEvent.click(within(historyDialog).getByRole("button", { name: "Copy history" }));

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "copy-history" }));
    expect(document.querySelector(".dialog-layer__html")).toHaveTextContent("Ready");
  });

  it("applies runtime text speed and dialog opacity from chat config", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        sprites: [
          { id: "mio", label: "Mio", path: "asset://mio.png" },
          { id: "ren", label: "Ren", path: "asset://ren.png" },
        ],
      }),
    );
    renderPage();

    await screen.findByText("Ready");
    fireEvent.click(screen.getByRole("button", { name: "Chat appearance settings" }));
    const config = await screen.findByRole("dialog", { name: "Chat appearance settings" });

    expect(within(config).queryByRole("button", { name: "Manage themes" })).not.toBeInTheDocument();

    const textSpeed = within(config).getByRole("slider", { name: "Text speed" });
    fireEvent.change(textSpeed, { target: { value: "96" } });
    expect(await within(config).findByText("96 chars/s")).toBeInTheDocument();

    const dialogOpacity = within(config).getByRole("slider", { name: "Dialog opacity" });
    fireEvent.change(dialogOpacity, { target: { value: "0.55" } });
    expect(await within(config).findByText("55%")).toBeInTheDocument();

    fireEvent.change(within(config).getByLabelText("Dialog fill color"), { target: { value: "#223344" } });
    fireEvent.change(within(config).getByRole("slider", { name: "Fill opacity" }), { target: { value: "0.7" } });
    const gradientFill = within(config).getByLabelText("Gradient fill");
    fireEvent.click(within(config).getByText("Gradient fill"));
    expect(gradientFill).toBeChecked();
    chooseCustomSelectOption(config, "Gradient type", "Two-color gradient");
    fireEvent.change(within(config).getByLabelText("Second fill color"), { target: { value: "#556677" } });

    const useMainColor = within(config).getByLabelText("Use main app color");
    expect(useMainColor).toBeChecked();
    fireEvent.click(within(config).getByText("Use main app color"));
    expect(useMainColor).not.toBeChecked();
    fireEvent.change(within(config).getByLabelText("Config menu color"), { target: { value: "#88cc44" } });

    const dialogScale = within(config).getByRole("slider", { name: "Dialog size" });
    fireEvent.change(dialogScale, { target: { value: "1.05" } });
    expect(await within(config).findByText("105%")).toBeInTheDocument();

    const mioScale = within(config).getByRole("slider", { name: "Sprite scale: Mio" });
    fireEvent.change(mioScale, { target: { value: "1.35" } });
    expect(await within(config).findByText("135%")).toBeInTheDocument();

    const renScale = within(config).getByRole("slider", { name: "Sprite scale: Ren" });
    fireEvent.change(renScale, { target: { value: "0.8" } });
    expect(await within(config).findByText("80%")).toBeInTheDocument();

    const spriteX = within(config).getByRole("slider", { name: "Sprite X" });
    fireEvent.change(spriteX, { target: { value: "72" } });
    expect(await within(config).findByText("72px")).toBeInTheDocument();

    const spriteY = within(config).getByRole("slider", { name: "Sprite Y" });
    fireEvent.change(spriteY, { target: { value: "-48" } });
    expect(await within(config).findByText("-48px")).toBeInTheDocument();

    const windowScale = within(config).getByRole("slider", { name: "Chat UI window scale" });
    fireEvent.change(windowScale, { target: { value: "1.1" } });
    expect(await within(config).findByText("110%")).toBeInTheDocument();

    fireEvent.change(within(config).getByLabelText("Nameplate font"), { target: { value: "Georgia" } });
    fireEvent.change(within(config).getByRole("slider", { name: "Nameplate font size" }), {
      target: { value: "19" },
    });
    fireEvent.change(within(config).getByLabelText("Nameplate text color"), { target: { value: "#ffeeaa" } });
    const nameBold = within(config).getByLabelText("Bold nameplate text");
    expect(nameBold).toBeChecked();
    fireEvent.click(within(config).getByText("Bold nameplate text"));
    expect(nameBold).not.toBeChecked();
    fireEvent.change(within(config).getByLabelText("Dialog font"), { target: { value: "Verdana" } });
    fireEvent.change(within(config).getByRole("slider", { name: "Dialog font size" }), { target: { value: "21" } });
    chooseCustomSelectOption(config, "Dialog text direction", "Right to left");
    chooseCustomSelectOption(config, "Dialog text alignment", "Right");
    fireEvent.change(within(config).getByLabelText("Dialog text color"), { target: { value: "#ddeeff" } });
    const dialogBold = within(config).getByLabelText("Bold dialog text");
    expect(dialogBold).not.toBeChecked();
    fireEvent.click(within(config).getByText("Bold dialog text"));
    expect(dialogBold).toBeChecked();

    await waitFor(() => {
      const stage = document.querySelector(".chat-stage") as HTMLElement;
      expect(stage.style.getPropertyValue("--chat-config-accent")).toBe("#88cc44");
      expect(stage.style.getPropertyValue("--chat-dialog-runtime-opacity")).toBe("0.55");
      expect(stage.style.getPropertyValue("--chat-dialog-runtime-scale")).toBe("1.05");
      expect(stage.style.getPropertyValue("--chat-dialog-composed-scale")).toBe("1.155");
      expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");
      expect(stage.style.getPropertyValue("--chat-dialog-runtime-background")).toBe(
        "linear-gradient(180deg, rgba(34, 51, 68, 0.7), rgba(85, 102, 119, 0.7))",
      );
      expect(stage.style.getPropertyValue("--chat-dialog-text-runtime-color")).toBe("#ddeeff");
      expect(stage.style.getPropertyValue("--chat-dialog-text-runtime-font-family")).toBe("Verdana");
      expect(stage.style.getPropertyValue("--chat-dialog-text-runtime-font-size")).toBe("21px");
      expect(stage.style.getPropertyValue("--chat-dialog-text-runtime-font-weight")).toBe("700");
      expect(stage.style.getPropertyValue("--chat-dialog-text-align")).toBe("right");
      expect(stage.style.getPropertyValue("--chat-dialog-text-direction")).toBe("rtl");
      expect(stage.style.getPropertyValue("--chat-name-runtime-color")).toBe("#ffeeaa");
      expect(stage.style.getPropertyValue("--chat-name-runtime-font-family")).toBe("Georgia");
      expect(stage.style.getPropertyValue("--chat-name-runtime-font-size")).toBe("19px");
      expect(stage.style.getPropertyValue("--chat-name-runtime-font-weight")).toBe("600");
      expect(stage.style.getPropertyValue("--chat-sprite-runtime-offset-x")).toBe("72px");
      expect(stage.style.getPropertyValue("--chat-sprite-runtime-offset-y")).toBe("-48px");
      expect(stage.style.getPropertyValue("--chat-toolbar-runtime-scale")).toBe("1.1");
      expect(stage.style.getPropertyValue("--chat-ui-runtime-width")).toBe("1120px");
      expect(stage.style.getPropertyValue("--chat-ui-window-scale")).toBe("1.1");
      const sprites = document.querySelectorAll<HTMLElement>(".sprite-layer__figure");
      expect(sprites[0]?.style.getPropertyValue("--sprite-scale")).toBe("1.35");
      expect(sprites[1]?.style.getPropertyValue("--sprite-scale")).toBe("0.8");
    });
    expect(JSON.parse(window.localStorage.getItem("shinsekai-chat-stage-runtime-config") || "{}")).toEqual({
      config: {
        alwaysOnTop: true,
        auto: false,
        autoHideInput: true,
        autoHideTopTools: true,
        bgmVolume: 1,
        configThemeColor: "#88cc44",
        configUseMainThemeColor: false,
        dialogText: {
          align: "right",
          alignOverride: true,
          bold: true,
          boldOverride: true,
          color: "#ddeeff",
          direction: "rtl",
          fontFamily: "Verdana",
          fontSize: 21,
        },
        dialogFill: {
          color: "#223344",
          color2: "#556677",
          gradient: true,
          gradientDirection: "to-bottom",
          gradientMode: "dual",
          opacity: 0.7,
        },
        dialogOpacity: 0.55,
        dialogScale: 1.05,
        immersiveMode: false,
        longPressTalk: false,
        nameText: {
          bold: false,
          boldOverride: true,
          color: "#ffeeaa",
          fontFamily: "Georgia",
          fontSize: 19,
        },
        spriteScales: {
          Mio: 1.35,
          Ren: 0.8,
        },
        spriteOffsetX: 72,
        spriteOffsetY: -48,
        typewriterCps: 96,
        windowScale: 1.1,
      },
      version: chatStageRuntimeConfigVersion,
    });
  });

  it("restores color and typography overrides to the active theme defaults", async () => {
    themeContextMocks.optional = {
      resolved: { typewriter: { cps: 42 } },
      style: {
        "--chat-dialog-text-theme-color": "#ddeeff",
        "--chat-dialog-text-theme-font-family": "Theme Dialog",
        "--chat-dialog-text-theme-font-size": "23px",
        "--chat-dialog-text-theme-font-weight": "600",
        "--chat-name-theme-color": "#ffccaa",
        "--chat-name-theme-font-family": "Theme Name",
        "--chat-name-theme-font-size": "19px",
        "--chat-name-theme-font-weight": "800",
        "--chat-theme-color": "#336699",
      } as CSSProperties,
    };
    window.localStorage.setItem(
      "shinsekai-chat-stage-runtime-config",
      JSON.stringify({
        config: {
          configThemeColor: "#ff3355",
          configUseMainThemeColor: false,
          dialogFill: {
            color: "#112233",
            color2: "#445566",
            gradient: true,
            gradientDirection: "to-top",
            gradientMode: "dual",
            opacity: 0.7,
          },
          dialogOpacity: 0.55,
          dialogText: {
            align: "right",
            alignOverride: true,
            bold: true,
            boldOverride: true,
            color: "#112233",
            direction: "rtl",
            fontFamily: "Verdana",
            fontSize: 25,
          },
          nameText: {
            bold: false,
            boldOverride: true,
            color: "#445566",
            fontFamily: "Georgia",
            fontSize: 21,
          },
          typewriterCps: 96,
          windowScale: 1.1,
        },
        version: chatStageRuntimeConfigVersion,
      }),
    );

    renderPage();

    await screen.findByText("Ready");
    fireEvent.click(screen.getByRole("button", { name: "Chat appearance settings" }));
    const config = await screen.findByRole("dialog", { name: "Chat appearance settings" });
    fireEvent.click(within(config).getByRole("button", { name: "Restore theme defaults" }));

    expect(within(config).getByLabelText("Config menu color")).toHaveValue("#336699");
    expect(within(config).getByLabelText("Use main app color")).not.toBeChecked();
    expect(within(config).getByLabelText("Nameplate text color")).toHaveValue("#ffccaa");
    expect(within(config).getByLabelText("Dialog text color")).toHaveValue("#ddeeff");
    expect(within(config).getByText("96 chars/s")).toBeInTheDocument();

    await waitFor(() => {
      const stage = document.querySelector(".chat-stage") as HTMLElement;
      expect(stage.style.getPropertyValue("--chat-config-accent")).toBe("#336699");
      expect(stage.style.getPropertyValue("--chat-dialog-runtime-background")).toBe("");
      expect(stage.style.getPropertyValue("--chat-dialog-runtime-opacity")).toBe("0.55");
      expect(stage.style.getPropertyValue("--chat-dialog-text-runtime-color")).toBe(
        "var(--chat-dialog-text-theme-color, #f7f1f0)",
      );
      expect(stage.style.getPropertyValue("--chat-name-runtime-color")).toBe("var(--chat-name-theme-color, #fff6f4)");
    });

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("shinsekai-chat-stage-runtime-config") || "{}");
      expect(stored).toMatchObject({
        config: {
          configThemeColor: "#336699",
          configUseMainThemeColor: false,
          dialogFill: defaultChatStageRuntimeConfig.dialogFill,
          dialogOpacity: 0.55,
          dialogText: {
            ...defaultChatStageRuntimeConfig.dialogText,
            direction: "rtl",
          },
          nameText: defaultChatStageRuntimeConfig.nameText,
          typewriterCps: 96,
          windowScale: 1.1,
        },
        version: chatStageRuntimeConfigVersion,
      });
    });
  });

  it("auto-hides top tools and input controls through independent immersive settings", async () => {
    renderPage();

    await screen.findByText("Ready");
    fireEvent.click(screen.getByRole("button", { name: "Chat appearance settings" }));
    const config = screen.getByRole("dialog", { name: "Chat appearance settings" });
    const immersiveMode = within(config).getByLabelText("Immersive mode");
    const autoHideTopTools = within(config).getByLabelText("Auto-hide top-right tools");
    const autoHideInput = within(config).getByLabelText("Auto-hide input controls");
    const topTools = document.querySelector(".top-stage-tools") as HTMLElement;
    const inputLayer = document.querySelector(".input-layer") as HTMLElement;

    expect(immersiveMode).toHaveClass("switch__input");
    expect(autoHideTopTools).toHaveClass("switch__input");
    expect(autoHideInput).toHaveClass("switch__input");
    expect(immersiveMode).not.toBeChecked();
    expect(autoHideTopTools).toBeChecked();
    expect(autoHideInput).toBeChecked();
    expect(autoHideTopTools).toBeDisabled();
    expect(autoHideInput).toBeDisabled();
    expect(topTools).toHaveAttribute("data-auto-hide", "false");
    expect(inputLayer).toHaveAttribute("data-auto-hide", "false");

    vi.useFakeTimers();
    fireEvent.click(immersiveMode);

    expect(autoHideTopTools).not.toBeDisabled();
    expect(autoHideInput).not.toBeDisabled();
    expect(topTools).toHaveAttribute("data-auto-hide", "true");
    expect(inputLayer).toHaveAttribute("data-auto-hide", "true");

    act(() => vi.advanceTimersByTime(600));
    expect(topTools).toHaveAttribute("data-visible", "false");
    expect(inputLayer).toHaveAttribute("data-visible", "false");
    expect(getComputedStyle(topTools).pointerEvents).toBe("none");
    expect(getComputedStyle(inputLayer).pointerEvents).toBe("none");

    fireEvent.pointerEnter(topTools);
    fireEvent.pointerEnter(inputLayer);
    expect(topTools).toHaveAttribute("data-visible", "true");
    expect(inputLayer).toHaveAttribute("data-visible", "true");

    fireEvent.pointerLeave(topTools);
    act(() => vi.advanceTimersByTime(599));
    expect(topTools).toHaveAttribute("data-visible", "true");
    act(() => vi.advanceTimersByTime(1));
    expect(topTools).toHaveAttribute("data-visible", "false");

    const textInput = screen.getByPlaceholderText("Enter dialogue");
    fireEvent.focus(textInput);
    fireEvent.pointerLeave(inputLayer);
    act(() => vi.advanceTimersByTime(600));
    expect(inputLayer).toHaveAttribute("data-visible", "true");
    fireEvent.blur(textInput);
    act(() => vi.advanceTimersByTime(600));
    expect(inputLayer).toHaveAttribute("data-visible", "false");

    fireEvent.change(textInput, { target: { value: "pending" } });
    act(() => vi.advanceTimersByTime(600));
    expect(inputLayer).toHaveAttribute("data-force-visible", "true");
    expect(inputLayer).toHaveAttribute("data-visible", "true");

    fireEvent.click(autoHideTopTools);
    expect(topTools).toHaveAttribute("data-auto-hide", "false");
    expect(topTools).toHaveAttribute("data-visible", "true");
    expect(inputLayer).toHaveAttribute("data-auto-hide", "true");
  });

  it("keeps the single ASR microphone visible and themed while it loads and listens", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    mocks.sendChatCommand.mockImplementation(async (command: ChatCommand) =>
      snapshot({
        asrEnabled: command.type === "resume-asr",
        asrLoading: command.type === "resume-asr",
        asrRunning: false,
        status: "paused",
      }),
    );
    themeContextMocks.optional = {
      resolved: { typewriter: { cps: 32 } },
      style: { "--chat-input-layout": "pill" } as CSSProperties,
    };
    window.localStorage.setItem(
      "shinsekai-chat-stage-runtime-config",
      JSON.stringify({ autoHideInput: true, immersiveMode: true }),
    );

    renderPage();

    await screen.findByText("Ready");
    const inputLayer = document.querySelector(".input-layer") as HTMLElement;
    fireEvent.click(screen.getByRole("button", { name: "More input actions" }));
    expect(inputLayer).toHaveAttribute("data-panel-open", "true");
    expect(inputLayer).toHaveAttribute("data-force-visible", "true");
    expect(inputLayer).toHaveAttribute("data-visible", "true");

    fireEvent.click(screen.getByRole("button", { name: "More input actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Resume ASR" }));
    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "resume-asr" }));

    const loadingButton = await screen.findByRole("button", { name: "Pause ASR" });
    expect(loadingButton).toHaveAttribute("aria-busy", "true");
    expect(loadingButton).toHaveAttribute("aria-pressed", "true");
    expect(loadingButton).toHaveClass("input-layer__asr-button--enabled", "input-layer__asr-button--loading");
    expect(inputLayer).toHaveAttribute("data-asr-enabled", "true");
    expect(inputLayer).toHaveAttribute("data-force-visible", "true");
    expect(inputLayer).toHaveAttribute("data-visible", "true");

    act(() => {
      listener?.({
        enabled: true,
        loading: false,
        running: true,
        seq: 1,
        ts: 1,
        type: "asr.state",
        v: 1,
      });
    });
    const listeningButton = screen.getByRole("button", { name: "Pause ASR" });
    expect(listeningButton).toHaveAttribute("aria-busy", "false");
    expect(listeningButton).toHaveClass("input-layer__asr-button--listening");
    expect(inputLayer).toHaveAttribute("data-listening", "true");

    fireEvent.click(listeningButton);
    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "pause-asr" }));
  });

  it("keeps ASR enabled through automatic submission and resumes after the final reply", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    renderPage();

    await screen.findByText("Ready");
    act(() => {
      listener?.({ enabled: true, loading: false, running: true, seq: 1, ts: 1, type: "asr.state", v: 1 });
      listener?.({ seq: 2, text: "hello wor", ts: 2, type: "asr.partial", v: 1 });
    });
    expect(screen.getByPlaceholderText("Enter dialogue")).toHaveValue("hello wor");

    act(() => {
      listener?.({ seq: 3, text: "hello world", ts: 3, type: "asr.final", v: 1 });
      listener?.({ enabled: true, loading: false, running: false, seq: 4, ts: 4, type: "asr.state", v: 1 });
    });
    expect(screen.getByText("hello world")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Enter dialogue")).toHaveValue("");
    const pausedForReplyButton = screen.getByRole("button", { name: "Pause ASR" });
    expect(pausedForReplyButton).toHaveAttribute("aria-pressed", "true");
    expect(pausedForReplyButton).not.toBeDisabled();
    expect(document.querySelector(".input-layer")).toHaveAttribute("data-listening", "false");
    expect(mocks.sendChatCommand).not.toHaveBeenCalledWith(expect.objectContaining({ type: "send-message" }));

    act(() => {
      listener?.({ seq: 5, ts: 5, type: "reply.finished", v: 1 });
      listener?.({ enabled: true, loading: false, running: true, seq: 6, ts: 6, type: "asr.state", v: 1 });
    });
    expect(document.querySelector(".input-layer")).toHaveAttribute("data-listening", "true");
    expect(screen.getByRole("button", { name: "Pause ASR" })).toHaveClass("input-layer__asr-button--listening");
  });

  it("resets immersive input focus when a closed session restores the input layer", async () => {
    let listener: ((event: ChatStageEvent) => void) | null = null;
    mocks.subscribeChatEvents.mockImplementation((next) => {
      listener = next;
      return vi.fn();
    });
    window.localStorage.setItem(
      "shinsekai-chat-stage-runtime-config",
      JSON.stringify({ autoHideInput: true, immersiveMode: true }),
    );

    renderPage();
    const input = await screen.findByPlaceholderText("Enter dialogue");
    fireEvent.focus(input);

    act(() => {
      listener?.({
        reason: "Session closed",
        seq: 1,
        ts: Date.now(),
        type: "session.closed",
        v: 1,
      });
    });
    expect(screen.queryByPlaceholderText("Enter dialogue")).not.toBeInTheDocument();

    vi.useFakeTimers();
    act(() => {
      listener?.({
        seq: 2,
        snapshot: snapshot({ eventSeq: 2, notificationText: "", sessionClosedReason: "" }),
        ts: Date.now(),
        type: "snapshot",
        v: 1,
      });
    });

    const restoredInput = screen.getByPlaceholderText("Enter dialogue");
    const restoredLayer = restoredInput.closest(".input-layer") as HTMLElement;
    act(() => vi.advanceTimersByTime(600));
    expect(restoredLayer).toHaveAttribute("data-visible", "false");
  });

  it("resolves theme text defaults for config controls", () => {
    const dialogText = effectiveChatStageTextStyle(
      defaultChatStageRuntimeConfig.dialogText,
      defaultChatStageRuntimeConfig.dialogText,
      {
        "--chat-dialog-text-theme-color": "#ffffff",
        "--chat-dialog-text-theme-font-family": "Georgia, serif",
        "--chat-dialog-text-theme-font-size": "34px",
        "--chat-dialog-text-theme-font-weight": "800",
      } as CSSProperties,
      "dialogText",
    );
    const nameText = effectiveChatStageTextStyle(
      defaultChatStageRuntimeConfig.nameText,
      defaultChatStageRuntimeConfig.nameText,
      {
        "--chat-name-theme-color": "#f0b72b",
        "--chat-name-theme-font-family": "Trebuchet MS, Georgia, serif",
        "--chat-name-theme-font-size": "30px",
        "--chat-name-theme-font-weight": "800",
      } as CSSProperties,
      "nameText",
    );

    expect(dialogText).toMatchObject({
      align: "center",
      bold: true,
      color: "#ffffff",
      direction: "ltr",
      fontFamily: "Georgia, serif",
      fontSize: 34,
    });
    expect(nameText).toMatchObject({
      bold: true,
      color: "#f0b72b",
      fontFamily: "Trebuchet MS, Georgia, serif",
      fontSize: 30,
    });
  });

  it("renders markdown dialog text and places the completion marker after the text", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        dialogText: "Ready **bold** `code` [link](https://example.com)",
      }),
    );

    renderPage();
    await screen.findByText("Ready");

    const dialogText = document.querySelector(".dialog-layer__text") as HTMLElement;
    expect(dialogText.querySelector("strong")).toHaveTextContent("bold");
    expect(dialogText.querySelector("code")).toHaveTextContent("code");
    const link = dialogText.querySelector("a") as HTMLAnchorElement;
    expect(link).toHaveAttribute("href", "https://example.com");
    const marker = dialogText.querySelector(".dialog-layer__ctc") as HTMLElement;
    expect(marker).not.toBeNull();
    expect(marker.parentElement).toBe(dialogText);
    expect(getComputedStyle(marker).position).not.toBe("absolute");

    fireEvent.click(link);
    expect(mocks.sendChatCommand).not.toHaveBeenCalledWith({ type: "dialog-advance" });
  });

  it("loads persisted runtime config before opening chat config", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      snapshot({
        sprites: [
          { id: "mio", label: "Mio", path: "asset://mio.png" },
          { id: "ren", label: "Ren", path: "asset://ren.png" },
        ],
      }),
    );
    window.localStorage.setItem(
      "shinsekai-chat-stage-runtime-config",
      JSON.stringify({
        dialogOpacity: 0.65,
        dialogScale: 1.1,
        spriteScales: {
          Mio: 1.4,
          Ren: 0.75,
        },
        spriteOffsetX: 36,
        spriteOffsetY: -24,
        typewriterCps: 42,
        windowScale: 1.15,
      }),
    );

    renderPage();

    await screen.findByText("Ready");
    const stage = document.querySelector(".chat-stage") as HTMLElement;
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-opacity")).toBe("0.65");
    expect(stage.style.getPropertyValue("--chat-sprite-runtime-offset-x")).toBe("36px");
    expect(stage.style.getPropertyValue("--chat-sprite-runtime-offset-y")).toBe("-24px");
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-scale")).toBe("1.1");
    expect(stage.style.getPropertyValue("--chat-dialog-composed-scale")).toBe("1.265");
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");
    expect(stage.style.getPropertyValue("--chat-toolbar-runtime-scale")).toBe("1.15");
    expect(stage.style.getPropertyValue("--chat-ui-runtime-width")).toBe("1120px");
    expect(stage.style.getPropertyValue("--chat-ui-window-scale")).toBe("1.15");
    const sprites = document.querySelectorAll<HTMLElement>(".sprite-layer__figure");
    expect(sprites[0]?.style.getPropertyValue("--sprite-scale")).toBe("1.4");
    expect(sprites[1]?.style.getPropertyValue("--sprite-scale")).toBe("0.75");

    fireEvent.click(screen.getByRole("button", { name: "Chat appearance settings" }));
    const config = screen.getByRole("dialog", { name: "Chat appearance settings" });

    expect(within(config).getByRole("slider", { name: "Text speed" })).toHaveValue("42");
    expect(within(config).getByRole("slider", { name: "Dialog opacity" })).toHaveValue("0.65");
    expect(within(config).getByRole("slider", { name: "Dialog size" })).toHaveValue("1.1");
    expect(within(config).getByRole("slider", { name: "Sprite scale: Mio" })).toHaveValue("1.4");
    expect(within(config).getByRole("slider", { name: "Sprite scale: Ren" })).toHaveValue("0.75");
    expect(within(config).getByRole("slider", { name: "Sprite X" })).toHaveValue("36");
    expect(within(config).getByRole("slider", { name: "Sprite Y" })).toHaveValue("-24");
    expect(within(config).getByRole("slider", { name: "Chat UI window scale" })).toHaveValue("1.15");
  });

  it("loads runtime history into the dialog and sends revert-history after confirmation", async () => {
    mocks.getChatHistory.mockResolvedValueOnce([
      { id: "history-0", role: "assistant", text: "Mio: Ready" },
      { id: "history-scene", role: "system", text: "SCENE: Hotel lobby" },
      { id: "history-bgm", role: "system", text: "bgm: calm.ogg" },
      { id: "history-scene-cn", role: "system", text: "场景：夜晚" },
      {
        createdAt: userHistoryCreatedAt,
        id: "history-1",
        revertUserIndex: 0,
        role: "user",
        text: "你: hello",
      },
    ] satisfies ChatHistoryEntry[]);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Open history" }));

    await waitFor(() => expect(mocks.getChatHistory).toHaveBeenCalledTimes(1));
    const dialog = await screen.findByRole("dialog", { name: "Conversation history" });
    expect(dialog).toHaveClass("chat-stage-modal");
    expect(dialog.querySelector(".chat-stage-modal__header")).not.toBeNull();
    expect(dialog.querySelector(".chat-stage-modal__summary")?.tagName).toBe("DIV");
    expect(within(dialog).getByRole("button", { name: "Copy history" })).toHaveTextContent("COPY");
    expect(within(dialog).getByRole("button", { name: "Clear history" })).toHaveTextContent("CLEAR");
    expect(within(dialog).getByText("2 entries")).toBeInTheDocument();
    const nameplates = dialog.querySelectorAll(".chat-history__nameplate");
    expect(nameplates).toHaveLength(2);
    expect(nameplates[0]).toHaveTextContent("Mio");
    expect(nameplates[0]).toHaveTextContent("Assistant");
    expect(nameplates[1]).toHaveTextContent("Aoi");
    expect(nameplates[1]).toHaveTextContent("User");
    expect(within(dialog).getByText("Mio")).toBeInTheDocument();
    expect(within(dialog).getByText("Ready")).toBeInTheDocument();
    expect(within(dialog).getByText("Aoi")).toBeInTheDocument();
    expect(within(dialog).getByText("#1")).toBeInTheDocument();
    expect(within(dialog).getByText("#2")).toBeInTheDocument();
    expect(within(dialog).queryByText("#3")).not.toBeInTheDocument();
    expect(
      within(dialog).getByText(
        new Date(userHistoryCreatedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("hello")).toBeInTheDocument();
    expect(within(dialog).queryByText("Hotel lobby")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("calm.ogg")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("夜晚")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Mio: Ready")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("你: hello")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Fork" }));
    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({ payload: { userIndex: 0 }, type: "fork-history" }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Open history" }));
    const reopenedDialog = await screen.findByRole("dialog", { name: "Conversation history" });
    fireEvent.click(within(reopenedDialog).getByRole("button", { name: "Revert to previous turn" }));

    const confirm = await screen.findByRole("dialog", { name: "Revert history" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Revert" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: 0,
        type: "revert-history",
      }),
    );
  });

  it("filters large history lists and renders them in batches", async () => {
    const entries = Array.from(
      { length: 130 },
      (_, index): ChatHistoryEntry => ({
        id: `history-${index}`,
        role: "assistant",
        text: index === 129 ? "Mio: target ending" : `Mio: filler ${index}`,
      }),
    );
    mocks.getChatHistory.mockResolvedValueOnce(entries);

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Open history" }));

    const dialog = await screen.findByRole("dialog", { name: "Conversation history" });
    await waitFor(() => expect(within(dialog).getByText("120 / 130 shown")).toBeInTheDocument());
    // The dialog opens on the newest messages, so the latest entry is visible and
    // the oldest entries are batched out of view until "show more".
    expect(within(dialog).getByText("target ending")).toBeInTheDocument();
    expect(within(dialog).queryByText("filler 0")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Show 10 more" }));
    expect(within(dialog).getByText("130 / 130 shown")).toBeInTheDocument();
    expect(within(dialog).getByText("filler 0")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByRole("searchbox", { name: "Search history" }), {
      target: { value: "target" },
    });
    expect(within(dialog).getByText("1 / 1 shown")).toBeInTheDocument();
    expect(within(dialog).getByText("target ending")).toBeInTheDocument();
    expect(within(dialog).queryByText("filler 1")).not.toBeInTheDocument();
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
        asrEnabled: true,
        asrLoading: false,
        asrRunning: true,
        notificationText: "",
        options: [],
        sessionClosedReason: "",
        status: "listening",
      }),
    );

    renderPage();

    await screen.findByText("聊天会话已结束。");
    expect(screen.queryByPlaceholderText("Enter dialogue")).not.toBeInTheDocument();

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

    const topControls = container.querySelector(".top-stage-tools__controls") as HTMLElement;
    expect(topControls.closest(".top-stage-tools")).toHaveAttribute("data-standalone-desktop", "true");
    expect(within(topControls).getByRole("button", { name: "Minimize" })).toBeInTheDocument();
    expect(within(topControls).getByRole("button", { name: "Maximize" })).toBeInTheDocument();
    expect(within(topControls).getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Drag window" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close chat" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Minimize" }));
    fireEvent.click(screen.getByRole("button", { name: "Maximize" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(desktopApiMocks.minimizeDesktopWindow).toHaveBeenCalledTimes(1));
    expect(desktopApiMocks.toggleMaximizeDesktopWindow).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(chatWindowMocks.closeChatSurface).toHaveBeenCalledTimes(1));
    expect(desktopApiMocks.closeDesktopWindow).not.toHaveBeenCalled();
    expect(desktopApiMocks.startDesktopWindowDrag).not.toHaveBeenCalled();

    fireEvent.mouseDown(container.querySelector(".sprite-layer__image")!, { button: 0 });
    await waitFor(() => expect(desktopApiMocks.startDesktopWindowDrag).toHaveBeenCalledTimes(1));
    expect(chatWindowMocks.closeChatSurface).toHaveBeenCalledTimes(1);
  });

  it("keeps an immersive standalone toolbar centered while hidden", async () => {
    desktopApiMocks.isTauriDesktop.mockReturnValue(true);
    window.localStorage.setItem(
      "shinsekai-chat-stage-runtime-config",
      JSON.stringify({ autoHideTopTools: true, immersiveMode: true }),
    );

    const { container } = renderPage(["/chat-stage"]);
    await screen.findByText("Ready");
    vi.useFakeTimers();

    const topTools = container.querySelector(".top-stage-tools") as HTMLElement;
    fireEvent.pointerLeave(topTools);
    act(() => vi.advanceTimersByTime(600));

    expect(topTools).toHaveAttribute("data-visible", "false");
  });
});
