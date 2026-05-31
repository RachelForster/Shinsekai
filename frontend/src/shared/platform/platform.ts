import { createBrowserPreviewPlatform } from "./browserPreviewPlatform";
import { createHttpPlatform } from "./httpPlatform";
import type { ShinsekaiPlatform } from "./types";

declare global {
  interface Window {
    __SHINSEKAI_IPC__?: ShinsekaiPlatform;
  }
}

let platform: ShinsekaiPlatform | null = null;

function bridgeBaseFromUrl() {
  const value = new URLSearchParams(window.location.search).get("shinsekai_bridge")?.trim();
  return value ?? "";
}

export function getPlatform(): ShinsekaiPlatform {
  if (!platform) {
    const httpBase = import.meta.env.VITE_SHINSEKAI_API_BASE?.trim();
    const desktopBridge = bridgeBaseFromUrl();
    const sameOriginBridge =
      !import.meta.env.DEV && /^https?:$/.test(window.location.protocol) ? window.location.origin : "";
    platform =
      window.__SHINSEKAI_IPC__ ??
      (httpBase
        ? createHttpPlatform(httpBase)
        : desktopBridge
          ? createHttpPlatform(desktopBridge)
          : sameOriginBridge
            ? createHttpPlatform(sameOriginBridge)
            : createBrowserPreviewPlatform());
  }
  return platform;
}
