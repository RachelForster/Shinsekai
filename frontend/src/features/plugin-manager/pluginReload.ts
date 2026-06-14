import { restartDesktopBridge } from "../../shared/desktop/desktopApi";

export async function reloadPluginService() {
  await waitForReloadAnimationFrame();
  const runtime = await restartDesktopBridge();
  await waitForPluginBridgeReady(runtime.bridgeUrl);
  return runtime;
}

function waitForReloadAnimationFrame() {
  if (typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => resolve());
    });
  });
}

async function waitForPluginBridgeReady(bridgeUrl: string, timeoutMs = 15000) {
  if (!bridgeUrl) {
    return;
  }
  const baseUrl = bridgeUrl.replace(/\/$/, "");
  const url = `${baseUrl}/api/health`;
  const started = Date.now();
  let lastError: unknown;

  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      const payload = await response.json().catch(() => null);
      if (response.ok && payload?.ok === true) {
        const status = normalizePluginLoadStatus(payload?.plugins) ?? (await fetchPluginLoadStatus(baseUrl));
        if (!status || status.status === "ready") {
          return;
        }
        if (status.status === "error") {
          throw new PluginLoadTerminalError(status.error || "Plugin service reload failed.");
        }
        lastError = new Error(`Plugin service is still ${status.status}.`);
      } else {
        lastError = new Error(`Plugin service health check failed: ${response.status}`);
      }
    } catch (error) {
      if (error instanceof PluginLoadTerminalError) {
        throw error;
      }
      lastError = error;
    }
    await delayPluginReload(160);
  }

  throw new Error(lastError instanceof Error ? lastError.message : `Timed out waiting for plugin service at ${url}`);
}

class PluginLoadTerminalError extends Error {}

type PluginLoadStatus = {
  error?: string;
  status?: string;
};

async function fetchPluginLoadStatus(baseUrl: string): Promise<PluginLoadStatus | null> {
  try {
    const response = await fetch(`${baseUrl}/api/plugins/status`, { cache: "no-store" });
    if (response.status === 404) {
      return null;
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return null;
    }
    return normalizePluginLoadStatus(payload);
  } catch {
    return null;
  }
}

function normalizePluginLoadStatus(value: unknown): PluginLoadStatus | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const status = typeof record.status === "string" ? record.status : "";
  if (!status) {
    return null;
  }
  return {
    error: typeof record.error === "string" ? record.error : "",
    status,
  };
}

function delayPluginReload(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
