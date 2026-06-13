import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatStagePage } from "../../../features/chat-stage/ChatStagePage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { createHttpPlatform } from "../../../shared/platform/httpPlatform";
import type { ChatSnapshot, ShinsekaiPlatform } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const platformMocks = vi.hoisted(() => ({
  getPlatform: vi.fn<() => ShinsekaiPlatform>(),
}));

const chatWindowMocks = vi.hoisted(() => ({
  closeChatSurface: vi.fn(),
}));

const desktopApiMocks = vi.hoisted(() => ({
  closeDesktopWindow: vi.fn(),
  isTauriDesktop: vi.fn(),
  minimizeDesktopWindow: vi.fn(),
  startDesktopWindowDrag: vi.fn(),
  toggleMaximizeDesktopWindow: vi.fn(),
}));

vi.mock("../../../shared/platform/platform", () => ({
  getPlatform: () => platformMocks.getPlatform(),
}));

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
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
    startDesktopWindowDrag: () => desktopApiMocks.startDesktopWindowDrag(),
    toggleMaximizeDesktopWindow: () => desktopApiMocks.toggleMaximizeDesktopWindow(),
  };
});

function mockJsonResponse(body: unknown, ok = true) {
  return Promise.resolve({
    json: () => Promise.resolve(body),
    ok,
    status: ok ? 200 : 400,
    statusText: ok ? "OK" : "Bad Request",
  } as Response);
}

function snapshot(overrides: Partial<ChatSnapshot> = {}): ChatSnapshot {
  return {
    backgroundPath: "asset://school.png",
    characterName: "Mio",
    dialogText: "Ready",
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

function renderPage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/"]}>
        <I18nProvider language="en">
          <ChatStagePage />
        </I18nProvider>
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("ChatStagePage http platform integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    desktopApiMocks.isTauriDesktop.mockReturnValue(false);
    chatWindowMocks.closeChatSurface.mockResolvedValue(undefined);
    desktopApiMocks.closeDesktopWindow.mockResolvedValue(undefined);
    desktopApiMocks.minimizeDesktopWindow.mockResolvedValue(undefined);
    desktopApiMocks.startDesktopWindowDrag.mockResolvedValue(undefined);
    desktopApiMocks.toggleMaximizeDesktopWindow.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    delete window.__SHINSEKAI_BRIDGE_RESTARTING__;
    delete window.__SHINSEKAI_RESTARTING__;
  });

  it("resolves local stage media paths through platform file URLs", async () => {
    const mediaSnapshot = snapshot({
      backgroundPath: "data/backgrounds/school.png",
      sprites: [{ id: "mio", label: "Mio", path: "data/characters/mio.png" }],
    });
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/chat/snapshot")) {
        return mockJsonResponse(mediaSnapshot);
      }
      if (url.endsWith("/api/chat/history")) {
        return mockJsonResponse([]);
      }
      if (url.endsWith("/api/chat/close")) {
        return mockJsonResponse(mediaSnapshot);
      }
      throw new Error(`Unexpected fetch in ChatStagePage media test: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);
    platformMocks.getPlatform.mockReturnValue(createHttpPlatform("http://127.0.0.1:8787"));

    renderPage();

    await screen.findByText("Ready");
    expect(document.querySelector(".chat-stage__background img")).toHaveAttribute(
      "src",
      "http://127.0.0.1:8787/api/media?path=data%2Fbackgrounds%2Fschool.png",
    );
    expect(document.querySelector(".sprite-layer__image")).toHaveAttribute(
      "src",
      "http://127.0.0.1:8787/api/media?path=data%2Fcharacters%2Fmio.png",
    );
  });

  it("reopens the input layer through repository and httpPlatform when a command clears closed-session markers", async () => {
    const closedSnapshot = snapshot({
      notificationText: "聊天会话已结束。",
      sessionClosedReason: "聊天会话已结束。",
      status: "paused",
    });
    const reopenedSnapshot = snapshot({
      dialogText: "语音识别已恢复。",
      notificationText: "",
      sessionClosedReason: "",
      status: "listening",
    });

    let commandIssued = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/chat/command")) {
        commandIssued = true;
        return mockJsonResponse(reopenedSnapshot);
      }
      if (url.endsWith("/api/chat/snapshot")) {
        return mockJsonResponse(commandIssued ? reopenedSnapshot : closedSnapshot);
      }
      if (url.endsWith("/api/chat/history")) {
        return mockJsonResponse([]);
      }
      if (url.endsWith("/api/chat/close")) {
        return mockJsonResponse(closedSnapshot);
      }
      throw new Error(`Unexpected fetch in ChatStagePage integration test: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", undefined);
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "cmd-integrated-reopen") });
    platformMocks.getPlatform.mockReturnValue(createHttpPlatform("http://127.0.0.1:8787"));

    renderPage();

    await screen.findByText("聊天会话已结束。");
    expect(screen.queryByPlaceholderText("Enter dialogue")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume ASR" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Resume ASR" }));

    await waitFor(() => expect(screen.getByPlaceholderText("Enter dialogue")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Pause ASR" })).toBeInTheDocument());
    expect(screen.queryByText("聊天会话已结束。")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/command",
      expect.objectContaining({
        body: JSON.stringify({ type: "resume-asr", cmdId: "cmd-integrated-reopen" }),
        method: "POST",
      }),
    );
  });
});
