import { createBrowserPreviewPlatform } from "./browserPreviewPlatform";
import { resolveBridgeEndpoint } from "./bridgeUrlContract";
import { createHttpPlatform } from "./httpPlatform";
import type { ShinsekaiPlatform } from "./types";

declare global {
  interface Window {
    __SHINSEKAI_IPC__?: ShinsekaiPlatform;
  }
}

let platform: ShinsekaiPlatform | null = null;

function bridgeBaseFromUrl() {
  const value = new URLSearchParams(window.location.search).get("shinsekai_bridge");
  return value ?? "";
}

function bridgeTokenFromUrl() {
  const value = new URLSearchParams(window.location.search).get("shinsekai_bridge_token")?.trim();
  return value ?? "";
}

function createBridgeHttpPlatform(baseUrl: string, token: string) {
  return token ? createHttpPlatform(baseUrl, token) : createHttpPlatform(baseUrl);
}

export function resolvePlatformHttpUrl(pathOrUrl: string): string {
  if (!pathOrUrl.startsWith("/api/") || typeof window === "undefined") {
    return pathOrUrl;
  }
  const desktopBridge = bridgeBaseFromUrl();
  const httpBase = import.meta.env.VITE_SHINSEKAI_API_BASE;
  const sameOriginBridge =
    !import.meta.env.DEV && /^https?:$/.test(window.location.protocol) ? window.location.origin : "";
  const baseUrl = desktopBridge || httpBase || sameOriginBridge;
  if (!baseUrl) {
    return pathOrUrl;
  }
  try {
    return resolveBridgeEndpoint(baseUrl, pathOrUrl).toString();
  } catch {
    return pathOrUrl;
  }
}

export function getPlatform(): ShinsekaiPlatform {
  if (!platform) {
    const httpBase = import.meta.env.VITE_SHINSEKAI_API_BASE;
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
