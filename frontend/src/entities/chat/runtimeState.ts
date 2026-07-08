import { useSyncExternalStore } from "react";

const listeners = new Set<() => void>();
let closingCount = 0;

function emitRuntimeState() {
  for (const listener of listeners) {
    listener();
  }
}

export function beginChatRuntimeClosing(): () => void {
  let released = false;
  closingCount += 1;
  emitRuntimeState();
  return () => {
    if (released) {
      return;
    }
    released = true;
    closingCount = Math.max(0, closingCount - 1);
    emitRuntimeState();
  };
}

export function isChatRuntimeClosing() {
  return closingCount > 0;
}

export function subscribeChatRuntimeState(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useChatRuntimeClosing() {
  return useSyncExternalStore(subscribeChatRuntimeState, isChatRuntimeClosing, isChatRuntimeClosing);
}
