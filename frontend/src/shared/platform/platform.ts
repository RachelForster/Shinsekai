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

function bridgeTokenFromUrl() {
  const value = new URLSearchParams(window.location.search).get("shinsekai_bridge_token")?.trim();
  return value ?? "";
}

function createBridgeHttpPlatform(baseUrl: string, token: string) {
  return token ? createHttpPlatform(baseUrl, token) : createHttpPlatform(baseUrl);
}

export function getPlatform(): ShinsekaiPlatform {
  if (!platform) {
    const httpBase = import.meta.env.VITE_SHINSEKAI_API_BASE?.trim();
    const httpToken = import.meta.env.VITE_SHINSEKAI_BRIDGE_TOKEN?.trim() ?? "";
    const desktopBridge = bridgeBaseFromUrl();
    const desktopBridgeToken = bridgeTokenFromUrl();
    const sameOriginBridge =
      !import.meta.env.DEV && /^https?:$/.test(window.location.protocol) ? window.location.origin : "";
    platform =
      window.__SHINSEKAI_IPC__ ??
      (desktopBridge
        ? createBridgeHttpPlatform(desktopBridge, desktopBridgeToken)
        : httpBase
          ? createBridgeHttpPlatform(httpBase, httpToken)
          : sameOriginBridge
            ? createBridgeHttpPlatform(sameOriginBridge, desktopBridgeToken)
            : createBrowserPreviewPlatform());
  }
  return platform;
}
