import type { ChatRuntimeProcessState, ChatSnapshot } from "./types";

export function runtimeStatusFromSnapshot(snapshot: ChatSnapshot): ChatRuntimeProcessState {
  const chatRuntimeClosing = Boolean(snapshot.chatRuntimeClosing);
  const chatProcessRunning = Boolean(snapshot.chatProcessRunning);

  return {
    chatProcessRunning,
    chatRuntimeClosing,
    state: chatRuntimeClosing ? "closing" : chatProcessRunning ? "running" : "idle",
  };
}
