import { useEffect } from "react";
import { getPlatform } from "../../../shared/platform/platform";

export function useDokiHandoffReceipt(historyPath?: string, sessionId?: string, connected?: boolean) {
  useEffect(() => {
    if (!historyPath || !sessionId || !connected) return;
    let current = true;
    const acknowledge = () =>
      getPlatform()
        .chat.ackDokiHandoff?.({ historyPath, sessionId })
        .catch(() => {});
    void acknowledge();
    const timer = window.setInterval(() => {
      if (current) void acknowledge();
    }, 5000);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [historyPath, sessionId, connected]);
}
