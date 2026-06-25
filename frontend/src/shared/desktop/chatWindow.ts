import { closeDesktopWindow, isTauriDesktop, openDesktopChatWindow, writeDesktopRestartDebugLog } from "./desktopApi";
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

function logChatWindow(message: string) {
  void writeDesktopRestartDebugLog(`ChatWindow ${message}`);
}

export async function showChatSurface(options: ShowChatSurfaceOptions = {}) {
  logChatWindow(
    `showChatSurface runtimeMode=${options.snapshot?.runtimeMode ?? ""} hasSession=${Boolean(
      options.snapshot?.sessionId,
    )} isTauri=${isTauriDesktop()}`,
  );
  if (!shouldShowReactChatSurface(options.snapshot)) {
    logChatWindow("showChatSurface skipped reason=native_runtime");
    return;
  }

  if (isTauriDesktop()) {
    await openDesktopChatWindow();
    logChatWindow("showChatSurface opened=desktop_chat_window");
    return;
  }

  const path = options.webPath ?? "/chat";
  if (options.navigate) {
    options.navigate(path);
    logChatWindow(`showChatSurface navigated path=${path}`);
    return;
  }

  if (typeof window !== "undefined") {
    window.location.hash = `#${path}`;
    logChatWindow(`showChatSurface hash path=${path}`);
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
  logChatWindow(
    `closeChatSurface runtimeMode=${options.snapshot?.runtimeMode ?? ""} hasSession=${Boolean(
      options.snapshot?.sessionId,
    )} closed=${Boolean(options.snapshot?.sessionClosedReason)} isTauri=${isTauriDesktop()}`,
  );
  if (isTauriDesktop()) {
    await closeDesktopWindow();
    logChatWindow("closeChatSurface closed=desktop_window");
    return;
  }

  if (options.closeRuntime && shouldCloseReactChatRuntime(options.snapshot)) {
    try {
      await options.closeRuntime();
      logChatWindow("closeChatSurface runtime_closed=true");
    } catch {
      // Ignore runtime close failures here and still allow the user to leave the chat surface.
      logChatWindow("closeChatSurface runtime_closed=false");
    }
  }

  const path = options.webPath ?? "/settings/launch";
  if (options.navigate) {
    options.navigate(path);
    logChatWindow(`closeChatSurface navigated path=${path}`);
    return;
  }

  if (typeof window !== "undefined") {
    window.location.hash = `#${path}`;
    logChatWindow(`closeChatSurface hash path=${path}`);
  }
}
