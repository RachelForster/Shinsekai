import { createBrowserPreviewPlatform } from "./browserPreviewPlatform";
import { createHttpPlatform } from "./httpPlatform";
import { getRemoteBridgeConfig, getRuntimeTarget, isRemotePcActive, isStandaloneRuntimeActive } from "./runtimeTarget";
import { createStandalonePlatform } from "./standalone";
import type { ShinsekaiPlatform } from "./types";

declare global {
  interface Window {
    __SHINSEKAI_IPC__?: ShinsekaiPlatform;
  }
}

let platform: ShinsekaiPlatform | null = null;
const modeChangeListeners = new Set<() => void>();

export function onPlatformModeChange(listener: () => void): () => void {
  modeChangeListeners.add(listener);
  return () => {
    modeChangeListeners.delete(listener);
  };
}

export function resetPlatformForModeSwitch(): void {
  platform = null;
  for (const listener of modeChangeListeners) {
    listener();
  }
}

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

export function resolvePlatformHttpUrl(pathOrUrl: string): string {
  if (!pathOrUrl.startsWith("/api/") || typeof window === "undefined") {
    return pathOrUrl;
  }
  const desktopBridge = bridgeBaseFromUrl();
  const httpBase = import.meta.env.VITE_SHINSEKAI_API_BASE?.trim();
  const explicitBase = desktopBridge || httpBase;
  if (explicitBase) {
    try {
      return new URL(pathOrUrl, explicitBase).toString();
    } catch {
      return pathOrUrl;
    }
  }
  if (isRemotePcActive()) {
    const remote = getRemoteBridgeConfig();
    if (remote.url) {
      try {
        return new URL(pathOrUrl, remote.url).toString();
      } catch {
        return pathOrUrl;
      }
    }
  }
  if (isStandaloneRuntimeActive()) {
    return pathOrUrl;
  }
  const sameOriginBridge =
    !import.meta.env.DEV && /^https?:$/.test(window.location.protocol) ? window.location.origin : "";
  if (!sameOriginBridge) {
    return pathOrUrl;
  }
  try {
    return new URL(pathOrUrl, sameOriginBridge).toString();
  } catch {
    return pathOrUrl;
  }
}

export function getPlatform(): ShinsekaiPlatform {
  if (!platform) {
    const httpBase = import.meta.env.VITE_SHINSEKAI_API_BASE?.trim();
    const httpToken = import.meta.env.VITE_SHINSEKAI_BRIDGE_TOKEN?.trim() ?? "";
    const desktopBridge = bridgeBaseFromUrl();
    const desktopBridgeToken = bridgeTokenFromUrl();
    const target = getRuntimeTarget();
    const remote = getRemoteBridgeConfig();
    const sameOriginBridge =
      !import.meta.env.DEV && /^https?:$/.test(window.location.protocol) ? window.location.origin : "";

    if (window.__SHINSEKAI_IPC__) {
      platform = window.__SHINSEKAI_IPC__;
    } else if (desktopBridge) {
      platform = createBridgeHttpPlatform(desktopBridge, desktopBridgeToken);
    } else if (httpBase) {
      platform = createBridgeHttpPlatform(httpBase, httpToken);
    } else if (target === "toy") {
      platform = createStandalonePlatform({ target: "toy" });
    } else if (isRemotePcActive() && remote.url) {
      platform = createBridgeHttpPlatform(remote.url, remote.token);
    } else if (isStandaloneRuntimeActive()) {
      platform = createStandalonePlatform({ target });
    } else if (sameOriginBridge) {
      platform = createBridgeHttpPlatform(sameOriginBridge, desktopBridgeToken);
    } else {
      platform = createBrowserPreviewPlatform();
    }
  }
  return platform;
}
