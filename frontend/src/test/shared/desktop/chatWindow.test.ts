import { afterEach, describe, expect, it, vi } from "vitest";

const desktopMocks = vi.hoisted(() => ({
  destroyDesktopChatWindow: vi.fn(),
  hideDesktopWindow: vi.fn(),
  isTauriDesktop: vi.fn(),
  openDesktopChatWindow: vi.fn(),
}));

vi.mock("../../../shared/desktop/desktopApi", () => ({
  destroyDesktopChatWindow: desktopMocks.destroyDesktopChatWindow,
  hideDesktopWindow: desktopMocks.hideDesktopWindow,
  isTauriDesktop: desktopMocks.isTauriDesktop,
  openDesktopChatWindow: desktopMocks.openDesktopChatWindow,
}));

import { closeChatSurface, showChatSurface } from "../../../shared/desktop/chatWindow";

describe("showChatSurface", () => {
  afterEach(() => {
    vi.clearAllMocks();
    window.location.hash = "";
  });

  it("opens the dedicated desktop chat window in Tauri", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(true);
    desktopMocks.openDesktopChatWindow.mockResolvedValue(undefined);
    const navigate = vi.fn();

    await showChatSurface({ navigate, snapshot: { runtimeMode: "react" } });

    expect(desktopMocks.openDesktopChatWindow).toHaveBeenCalledTimes(1);
    expect(navigate).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
  });

  it("navigates with the provided router callback in browser mode", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(false);
    const navigate = vi.fn();

    await showChatSurface({ navigate, snapshot: { runtimeMode: "react" }, webPath: "/chat-stage" });

    expect(navigate).toHaveBeenCalledWith("/chat-stage");
    expect(window.location.hash).toBe("");
  });

  it("falls back to updating the hash route when no router callback is available", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(false);

    await showChatSurface({ snapshot: { runtimeMode: "react" } });

    expect(window.location.hash).toBe("#/chat");
  });

  it("does not open the React chat surface when the backend launched native chat", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(true);
    desktopMocks.openDesktopChatWindow.mockResolvedValue(undefined);
    const navigate = vi.fn();

    await showChatSurface({ navigate, snapshot: { runtimeMode: "native" } });

    expect(desktopMocks.openDesktopChatWindow).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
  });

  it("hides the dedicated desktop chat window before closing the runtime, then destroys it", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(true);
    const order: string[] = [];
    let resolveClose: () => void = () => {};
    const closeRuntime = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          order.push("runtime-started");
          resolveClose = resolve;
        }),
    );
    desktopMocks.hideDesktopWindow.mockImplementation(async () => {
      order.push("window-hidden");
    });
    desktopMocks.destroyDesktopChatWindow.mockImplementation(async () => {
      order.push("window-destroyed");
    });
    const navigate = vi.fn();

    const closePromise = closeChatSurface({
      closeRuntime,
      navigate,
      snapshot: { runtimeMode: "react", sessionId: "session-1", wsUrl: "ws://127.0.0.1:8788/ws" },
    });

    await vi.waitFor(() => expect(closeRuntime).toHaveBeenCalledTimes(1));
    expect(desktopMocks.hideDesktopWindow).toHaveBeenCalledTimes(1);
    expect(order).toEqual(["window-hidden", "runtime-started"]);
    expect(desktopMocks.destroyDesktopChatWindow).not.toHaveBeenCalled();
    resolveClose();
    await closePromise;
    expect(desktopMocks.destroyDesktopChatWindow).toHaveBeenCalledTimes(1);
    expect(order).toEqual(["window-hidden", "runtime-started", "window-destroyed"]);
    expect(navigate).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
  });

  it("navigates back to launch when closing the chat surface in browser mode", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(false);
    const navigate = vi.fn();

    await closeChatSurface({ navigate });

    expect(navigate).toHaveBeenCalledWith("/settings/launch");
    expect(window.location.hash).toBe("");
  });

  it("leaves the browser chat surface before the live runtime finishes closing", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(false);
    let resolveClose: () => void = () => {};
    const closeRuntime = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveClose = resolve;
        }),
    );
    const navigate = vi.fn();

    const closePromise = closeChatSurface({
      closeRuntime,
      navigate,
      snapshot: {
        runtimeMode: "react",
        sessionId: "session-1",
        wsUrl: "ws://127.0.0.1:8788/ws",
      },
    });

    expect(closeRuntime).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/settings/launch");
    resolveClose();
    await closePromise;
  });

  it("does not close the runtime when the chat surface is already closed or native", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(false);
    const closeRuntime = vi.fn().mockResolvedValue(undefined);

    await closeChatSurface({
      closeRuntime,
      snapshot: {
        runtimeMode: "native",
        sessionId: "session-1",
        wsUrl: "ws://127.0.0.1:8788/ws",
      },
    });
    await closeChatSurface({
      closeRuntime,
      snapshot: {
        runtimeMode: "react",
        sessionClosedReason: "聊天会话已结束。",
        sessionId: "session-1",
        wsUrl: "ws://127.0.0.1:8788/ws",
      },
    });

    expect(closeRuntime).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("#/settings/launch");
  });
});
