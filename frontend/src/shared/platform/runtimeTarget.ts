export type RuntimeTarget = "desktop" | "mobile" | "toy" | "web";
export type MobileConnectionMode = "standalone" | "remote-pc";

export interface RemoteBridgeConfig {
  mode: MobileConnectionMode;
  url: string;
  token: string;
}

const REMOTE_BRIDGE_STORAGE_KEY = "shinsekai-remote-bridge-v1";
export const RUNTIME_MODE_CHANGE_EVENT = "shinsekai:runtime-mode-change";
const DEFAULT_REMOTE_BRIDGE_CONFIG: RemoteBridgeConfig = {
  mode: "standalone",
  url: "",
  token: "",
};

function hasToyContainer(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return Boolean((window as Window & { toy?: unknown }).toy);
}

function isMobileUserAgent(): boolean {
  if (typeof navigator === "undefined") {
    return false;
  }
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent ?? "");
}

function hasTauriInternals(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return (
    Boolean(window.__TAURI_INTERNALS__) ||
    window.location.protocol === "shinsekai:" ||
    window.location.protocol === "tauri:" ||
    window.location.hostname === "tauri.localhost"
  );
}

export function getRuntimeTarget(): RuntimeTarget {
  const explicit = import.meta.env.VITE_SHINSEKAI_TARGET?.trim().toLowerCase();
  if (explicit === "toy" || explicit === "mobile" || explicit === "desktop" || explicit === "web") {
    return explicit;
  }
  if (hasToyContainer()) {
    return "toy";
  }
  if (hasTauriInternals()) {
    return isMobileUserAgent() ? "mobile" : "desktop";
  }
  return "web";
}

export function getRemoteBridgeConfig(): RemoteBridgeConfig {
  if (typeof window === "undefined") {
    return { ...DEFAULT_REMOTE_BRIDGE_CONFIG };
  }
  try {
    const raw = window.localStorage?.getItem(REMOTE_BRIDGE_STORAGE_KEY);
    if (!raw) {
      return { ...DEFAULT_REMOTE_BRIDGE_CONFIG };
    }
    const parsed = JSON.parse(raw) as Partial<RemoteBridgeConfig> | null;
    if (!parsed || typeof parsed !== "object") {
      return { ...DEFAULT_REMOTE_BRIDGE_CONFIG };
    }
    return {
      mode: parsed.mode === "remote-pc" ? "remote-pc" : "standalone",
      url: typeof parsed.url === "string" ? parsed.url.trim() : "",
      token: typeof parsed.token === "string" ? parsed.token.trim() : "",
    };
  } catch {
    return { ...DEFAULT_REMOTE_BRIDGE_CONFIG };
  }
}

export function saveRemoteBridgeConfig(patch: Partial<RemoteBridgeConfig>): RemoteBridgeConfig {
  const current = getRemoteBridgeConfig();
  const next: RemoteBridgeConfig = {
    mode: patch.mode ?? current.mode,
    url: patch.url !== undefined ? patch.url.trim().replace(/\/+$/, "") : current.url,
    token: patch.token !== undefined ? patch.token.trim() : current.token,
  };
  if (typeof window !== "undefined") {
    try {
      window.localStorage?.setItem(REMOTE_BRIDGE_STORAGE_KEY, JSON.stringify(next));
      window.dispatchEvent(new Event(RUNTIME_MODE_CHANGE_EVENT));
    } catch {
      // Ignore storage quota/security errors in restricted contexts.
    }
  }
  return next;
}

export function hasExplicitBridgeOverride(): boolean {
  if (typeof window !== "undefined") {
    const bridgeParam = new URLSearchParams(window.location.search).get("shinsekai_bridge")?.trim();
    if (bridgeParam) {
      return true;
    }
  }
  return Boolean(import.meta.env.VITE_SHINSEKAI_API_BASE?.trim());
}

export function canConnectRemotePc(): boolean {
  const target = getRuntimeTarget();
  return (
    target === "mobile" ||
    (target === "web" && (import.meta.env.VITE_SHINSEKAI_STANDALONE === "true" || isRemotePcActive()))
  );
}

export function isRemotePcActive(): boolean {
  const target = getRuntimeTarget();
  if (target === "toy" || target === "desktop") {
    return false;
  }
  if (hasExplicitBridgeOverride()) {
    return false;
  }
  const config = getRemoteBridgeConfig();
  return config.mode === "remote-pc" && Boolean(config.url.trim());
}

export function isStandaloneRuntimeActive(): boolean {
  if (hasExplicitBridgeOverride()) {
    return false;
  }
  const target = getRuntimeTarget();
  if (target === "toy") {
    return true;
  }
  if (import.meta.env.VITE_SHINSEKAI_STANDALONE === "true") {
    return !isRemotePcActive();
  }
  if (target === "mobile") {
    const config = getRemoteBridgeConfig();
    return config.mode !== "remote-pc" || !config.url.trim();
  }
  return false;
}
