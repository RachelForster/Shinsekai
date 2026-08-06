import {
  destroyDesktopChatWindow,
  hideDesktopWindow,
  isTauriDesktop,
  openDesktopChatWindow,
  writeDesktopRestartDebugLog,
} from "./desktopApi";
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
  const closeRuntime = () =>
    options.closeRuntime && shouldCloseReactChatRuntime(options.snapshot)
      ? options.closeRuntime().then(
          () => {
            logChatWindow("closeChatSurface runtime_closed=true");
          },
          () => {
            // Ignore runtime close failures here and still allow the user to leave the chat surface.
            logChatWindow("closeChatSurface runtime_closed=false");
          },
        )
      : undefined;

  if (isTauriDesktop()) {
    await hideDesktopWindow().catch(() => {
      // Continue closing the runtime even if the shell could not hide the window.
    });
    logChatWindow("closeChatSurface hidden=desktop_window");
    await closeRuntime();
    await destroyDesktopChatWindow().catch(() => {
      // The runtime is already closed; a shell failure must not restart the close flow.
    });
    logChatWindow("closeChatSurface destroyed=desktop_window");
    return;
  }

  const closeRuntimePromise = closeRuntime();
  const path = options.webPath ?? "/settings/launch";
  if (options.navigate) {
    options.navigate(path);
    logChatWindow(`closeChatSurface navigated path=${path}`);
  } else if (typeof window !== "undefined") {
    window.location.hash = `#${path}`;
    logChatWindow(`closeChatSurface hash path=${path}`);
  }

  await closeRuntimePromise;
}
