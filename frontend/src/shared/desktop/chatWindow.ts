import { destroyDesktopChatWindow, hideDesktopWindow, isTauriDesktop, openDesktopChatWindow } from "./desktopApi";
import type { ChatSnapshot } from "../platform/types";

interface ShowChatSurfaceOptions {
  navigate?: (path: string) => void;
  snapshot?: Pick<ChatSnapshot, "runtimeMode" | "sessionId" | "wsUrl"> | null;
  webPath?: string;
}

function shouldShowReactChatSurface(snapshot?: Pick<ChatSnapshot, "runtimeMode" | "sessionId" | "wsUrl"> | null) {
  if (snapshot?.runtimeMode === "native") {
    return false;
  }
  if (snapshot?.runtimeMode === "react") {
    return true;
  }
  if (snapshot && (snapshot.sessionId || snapshot.wsUrl)) {
    return true;
  }
  return true;
}

export async function showChatSurface(options: ShowChatSurfaceOptions = {}) {
  if (!shouldShowReactChatSurface(options.snapshot)) {
    return;
  }

  if (isTauriDesktop()) {
    await openDesktopChatWindow();
    return;
  }

  const path = options.webPath ?? "/chat";
  if (options.navigate) {
    options.navigate(path);
    return;
  }

  if (typeof window !== "undefined") {
    window.location.hash = `#${path}`;
  }
}

interface CloseChatSurfaceOptions {
  closeRuntime?: () => Promise<unknown>;
  navigate?: (path: string) => void;
  snapshot?: Pick<ChatSnapshot, "runtimeMode" | "sessionClosedReason" | "sessionId" | "wsUrl"> | null;
  webPath?: string;
}

function shouldCloseReactChatRuntime(
  snapshot?: Pick<ChatSnapshot, "runtimeMode" | "sessionClosedReason" | "sessionId" | "wsUrl"> | null,
) {
  if (snapshot?.runtimeMode === "native") {
    return false;
  }
  if (snapshot?.sessionClosedReason) {
    return false;
  }
  return Boolean(snapshot?.sessionId || snapshot?.wsUrl);
}

export async function closeChatSurface(options: CloseChatSurfaceOptions = {}) {
  const closeRuntime = () =>
    options.closeRuntime && shouldCloseReactChatRuntime(options.snapshot)
      ? options.closeRuntime().catch(() => {
          // Ignore runtime close failures here and still allow the user to leave the chat surface.
        })
      : undefined;

  if (isTauriDesktop()) {
    await hideDesktopWindow().catch(() => {
      // Continue closing the runtime even if the shell could not hide the window.
    });
    await closeRuntime();
    await destroyDesktopChatWindow().catch(() => {
      // The runtime is already closed; a shell failure must not restart the close flow.
    });
    return;
  }

  const closeRuntimePromise = closeRuntime();
  const path = options.webPath ?? "/settings/launch";
  if (options.navigate) {
    options.navigate(path);
  } else if (typeof window !== "undefined") {
    window.location.hash = `#${path}`;
  }

  await closeRuntimePromise;
}
