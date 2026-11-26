import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatStagePage } from "../../../features/chat-stage/ChatStagePage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { ChatSnapshot } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const repoMocks = vi.hoisted(() => ({
  getChatHistory: vi.fn(),
  getChatSnapshot: vi.fn(),
  getChatTheme: vi.fn(),
  subscribeChatEvents: vi.fn(),
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

const windowViewportMocks = vi.hoisted(() => ({
  isDesktopWindowExpanded: vi.fn(),
  resizeListener: null as null | (() => void),
}));

vi.mock("../../../entities/chat/repository", () => ({
  closeChat: vi.fn().mockResolvedValue({}),
  getChatHistory: () => repoMocks.getChatHistory(),
  getChatHistoryVoice: vi.fn().mockResolvedValue([]),
  getChatReplay: () => new Promise(() => {}),
  getChatSnapshot: () => repoMocks.getChatSnapshot(),
  getChatTheme: () => repoMocks.getChatTheme(),
  sendChatCommand: vi.fn().mockResolvedValue({}),
  subscribeChatEvents: (listener: () => void) => repoMocks.subscribeChatEvents(listener),
  uploadChatAttachments: vi.fn().mockResolvedValue({ attachments: [] }),
}));

vi.mock("../../../entities/config/repository", () => ({
  getAppConfig: vi.fn().mockResolvedValue({ api_config: {} }),
}));

vi.mock("../../../entities/files/repository", () => ({
  browseFiles: vi.fn().mockResolvedValue({ cwd: "", entries: [], roots: [] }),
  fileUrl: (path: string) => path,
}));

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
}));

vi.mock("../../../shared/desktop/chatWindow", () => ({
  closeChatSurface: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/desktop/desktopApi")>();
  return {
    ...actual,
    closeDesktopWindow: () => desktopApiMocks.closeDesktopWindow(),
    getDesktopWindowCursorPosition: () => desktopApiMocks.getDesktopWindowCursorPosition(),
    isTauriDesktop: () => desktopApiMocks.isTauriDesktop(),
    minimizeDesktopWindow: () => desktopApiMocks.minimizeDesktopWindow(),
    setDesktopChatWindowMiniInputShortcut: vi.fn().mockResolvedValue({ error: null, registered: false }),
    setDesktopChatWindowMiniMode: vi.fn().mockResolvedValue({ dockSide: "right" }),
    setDesktopWindowAlwaysOnTop: (alwaysOnTop: boolean) => desktopApiMocks.setDesktopWindowAlwaysOnTop(alwaysOnTop),
    setDesktopWindowClickThrough: (ignore: boolean) => desktopApiMocks.setDesktopWindowClickThrough(ignore),
    startDesktopWindowDrag: () => desktopApiMocks.startDesktopWindowDrag(),
    startDesktopWindowResize: (direction: string) => desktopApiMocks.startDesktopWindowResize(direction),
    syncDesktopChatWindowMiniLayout: vi.fn().mockResolvedValue({ dockSide: "right" }),
    toggleMaximizeDesktopWindow: () => desktopApiMocks.toggleMaximizeDesktopWindow(),
  };
});

vi.mock("../../../shared/desktop/windowViewport", () => ({
  isDesktopWindowExpanded: () => windowViewportMocks.isDesktopWindowExpanded(),
  subscribeDesktopWindowResize: (listener: () => void) => {
    windowViewportMocks.resizeListener = listener;
    return Promise.resolve(() => {
      if (windowViewportMocks.resizeListener === listener) {
        windowViewportMocks.resizeListener = null;
      }
    });
  },
}));

function setWindowSize(width: number, height: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: width });
  Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: height });
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function makeSnapshot(overrides: Partial<ChatSnapshot> = {}): ChatSnapshot {
  return {
    backgroundPath: "asset://school.png",
    characterName: "Mio",
    dialogText: "Hello world",
    historyEntries: [],
    historyPath: "data/chat_history/default.json",
    inputDraft: "",
    options: [],
    sprites: [],
    status: "idle",
    voiceLanguage: "ja",
    ...overrides,
  };
}

function renderStage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/chat-stage"]}>
        <I18nProvider language="en">
          <ChatStagePage />
        </I18nProvider>
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("ChatStagePage fullscreen visual-novel dialog adaptation", () => {
  const originalWidth = window.innerWidth;
  const originalHeight = window.innerHeight;
  const originalFullscreenDescriptor = Object.getOwnPropertyDescriptor(document, "fullscreenElement");

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
    setWindowSize(1024, 768);
    windowViewportMocks.resizeListener = null;
    windowViewportMocks.isDesktopWindowExpanded.mockResolvedValue(false);
    desktopApiMocks.isTauriDesktop.mockReturnValue(false);
    desktopApiMocks.getDesktopWindowCursorPosition.mockResolvedValue({ x: 0, y: 0 });
    desktopApiMocks.setDesktopWindowAlwaysOnTop.mockResolvedValue(undefined);
    desktopApiMocks.setDesktopWindowClickThrough.mockResolvedValue(undefined);
    repoMocks.getChatSnapshot.mockResolvedValue(makeSnapshot());
    repoMocks.getChatHistory.mockResolvedValue([]);
    repoMocks.getChatTheme.mockResolvedValue({});
    repoMocks.subscribeChatEvents.mockReturnValue(vi.fn());
  });

  afterEach(() => {
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
    setWindowSize(originalWidth, originalHeight);
    if (originalFullscreenDescriptor) {
      Object.defineProperty(document, "fullscreenElement", originalFullscreenDescriptor);
    } else {
      delete (document as unknown as { fullscreenElement?: Element | null }).fullscreenElement;
    }
  });

  it("switches to VN dialog proportions on resize to 1080p and restores on return to windowed size", async () => {
    renderStage();
    const stage = await waitFor(() => document.querySelector<HTMLElement>(".chat-stage")!);
    expect(stage.dataset.viewportVn).toBe("false");
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");
    expect(stage.style.getPropertyValue("--chat-option-font-size")).toBe("");
    expect(stage.style.getPropertyValue("--chat-option-min-height")).toBe("");

    act(() => {
      setWindowSize(1920, 1080);
      fireEvent(window, new Event("resize"));
    });

    await waitFor(() => expect(stage.dataset.viewportVn).toBe("true"));
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1651px");
    expect(stage.style.getPropertyValue("--chat-dialog-min-height")).toBe("216px");
    expect(stage.style.getPropertyValue("--chat-dialog-text-runtime-font-size")).toBe("24px");
    expect(stage.style.getPropertyValue("--chat-option-font-size")).toBe("22px");
    expect(stage.style.getPropertyValue("--chat-option-min-height")).toBe("63px");

    act(() => {
      setWindowSize(1280, 820);
      fireEvent(window, new Event("resize"));
    });

    await waitFor(() => expect(stage.dataset.viewportVn).toBe("false"));
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");
    expect(stage.style.getPropertyValue("--chat-option-font-size")).toBe("");
    expect(stage.style.getPropertyValue("--chat-option-min-height")).toBe("");
  });

  it("activates VN adaptation on browser fullscreenchange even at 1280x720", async () => {
    setWindowSize(1280, 720);
    renderStage();
    const stage = await waitFor(() => document.querySelector<HTMLElement>(".chat-stage")!);
    expect(stage.dataset.viewportVn).toBe("false");

    act(() => {
      Object.defineProperty(document, "fullscreenElement", { configurable: true, value: stage });
      fireEvent(document, new Event("fullscreenchange"));
    });

    await waitFor(() => expect(stage.dataset.viewportVn).toBe("true"));
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1101px");
  });

  it("activates on Tauri desktop maximize and disables VN adaptation when miniAvatarMode is enabled", async () => {
    setWindowSize(1280, 720);
    desktopApiMocks.isTauriDesktop.mockReturnValue(true);
    windowViewportMocks.isDesktopWindowExpanded.mockResolvedValue(true);

    renderStage();
    const stage = await waitFor(() => document.querySelector<HTMLElement>(".chat-stage")!);
    await waitFor(() => expect(stage.dataset.viewportVn).toBe("true"));
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1101px");
    expect(stage.style.getPropertyValue("--chat-option-font-size")).toBe("17px");
    expect(stage.style.getPropertyValue("--chat-option-min-height")).toBe("48px");

    const miniButton = stage.querySelector<HTMLButtonElement>(".top-stage-tools__button--mini-avatar");
    expect(miniButton).not.toBeNull();
    fireEvent.click(miniButton!);

    await waitFor(() => expect(stage.dataset.miniAvatar).toBe("true"));
    expect(stage.dataset.viewportVn).toBe("false");
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");
    expect(stage.style.getPropertyValue("--chat-option-font-size")).toBe("");
    expect(stage.style.getPropertyValue("--chat-option-min-height")).toBe("");
  });

  it("ignores stale desktop expanded query results that resolve out of order after restoring to 1280x720", async () => {
    setWindowSize(1280, 720);
    desktopApiMocks.isTauriDesktop.mockReturnValue(true);

    const initialQuery = createDeferred<boolean>();
    const staleMaximizeQuery = createDeferred<boolean>();
    const restoreQuery = createDeferred<boolean>();
    const earlierPendingQuery = createDeferred<boolean>();
    const latestRestoreQuery = createDeferred<boolean>();

    windowViewportMocks.isDesktopWindowExpanded
      .mockReturnValueOnce(initialQuery.promise)
      .mockReturnValueOnce(staleMaximizeQuery.promise)
      .mockReturnValueOnce(restoreQuery.promise)
      .mockReturnValueOnce(earlierPendingQuery.promise)
      .mockReturnValueOnce(latestRestoreQuery.promise);

    renderStage();
    const stage = await waitFor(() => document.querySelector<HTMLElement>(".chat-stage")!);
    await waitFor(() => expect(windowViewportMocks.resizeListener).not.toBeNull());

    await act(async () => {
      initialQuery.resolve(true);
      await Promise.resolve();
    });

    await waitFor(() => expect(stage.dataset.viewportVn).toBe("true"));
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1101px");

    act(() => {
      windowViewportMocks.resizeListener?.();
    });
    act(() => {
      fireEvent(window, new Event("resize"));
    });

    await act(async () => {
      restoreQuery.resolve(false);
      await Promise.resolve();
    });

    await waitFor(() => expect(stage.dataset.viewportVn).toBe("false"));
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");

    await act(async () => {
      staleMaximizeQuery.resolve(true);
      await Promise.resolve();
    });

    expect(stage.dataset.viewportVn).toBe("false");
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");

    act(() => {
      windowViewportMocks.resizeListener?.();
    });
    act(() => {
      fireEvent(window, new Event("resize"));
    });

    await act(async () => {
      earlierPendingQuery.resolve(true);
      await Promise.resolve();
    });

    expect(stage.dataset.viewportVn).toBe("false");
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");

    await act(async () => {
      latestRestoreQuery.resolve(false);
      await Promise.resolve();
    });

    expect(stage.dataset.viewportVn).toBe("false");
    expect(stage.style.getPropertyValue("--chat-dialog-runtime-width")).toBe("1040px");
    expect(windowViewportMocks.isDesktopWindowExpanded).toHaveBeenCalledTimes(5);
  });
});
