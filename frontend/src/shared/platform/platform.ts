import { createBrowserPreviewPlatform } from "./browserPreviewPlatform";
import { createHttpPlatform } from "./httpPlatform";
import type { ShinsekaiPlatform } from "./types";

declare global {
  interface Window {
    __SHINSEKAI_IPC__?: ShinsekaiPlatform;
  }
}

let platform: ShinsekaiPlatform | null = null;

export function getPlatform(): ShinsekaiPlatform {
  if (!platform) {
    const httpBase = import.meta.env.VITE_SHINSEKAI_API_BASE?.trim();
    const sameOriginBridge =
      !import.meta.env.DEV && /^https?:$/.test(window.location.protocol) ? window.location.origin : "";
    platform =
      window.__SHINSEKAI_IPC__ ??
      (httpBase
        ? createHttpPlatform(httpBase)
        : sameOriginBridge
          ? createHttpPlatform(sameOriginBridge)
          : createBrowserPreviewPlatform());
  }
  return platform;
}
