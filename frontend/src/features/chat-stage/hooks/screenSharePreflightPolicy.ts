import type { PerceptionLocalServerStatus, PerceptionStatusResponse } from "../../../shared/platform/types";

export type ScreenSharePreflightPhase =
  | "idle"
  | "checking"
  | "setup_needed"
  | "installing"
  | "starting"
  | "ready"
  | "error";

export type ScreenSharePreflightErrorKind =
  | "check_timeout"
  | "model_mismatch"
  | "unreachable"
  | "server_failed"
  | "setup_error"
  | "missing_gguf"
  | "unknown";

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "0.0.0.0", "::1"]);

export function isLocalPerceptionBaseUrl(baseUrl: string | undefined): boolean {
  const clean = (baseUrl || "").trim();
  if (!clean) return true;
  try {
    const parsed = new URL(clean);
    if (parsed.protocol !== "http:") return false;
    return LOCAL_HOSTS.has(parsed.hostname.replace(/^\[|\]$/g, "").toLowerCase());
  } catch {
    return false;
  }
}

export function isPerceptionServiceReady(response: PerceptionStatusResponse): boolean {
  return Boolean(response.health?.ok && response.health.modelPresent !== false);
}

export function isSameLocalTarget(
  localServer: PerceptionLocalServerStatus | undefined,
  config: PerceptionStatusResponse["config"] | undefined,
): boolean {
  if (!localServer || !config) return false;
  const srvBase = localServer.baseUrl.trim().replace(/\/+$/, "");
  const cfgBase = config.baseUrl.trim().replace(/\/+$/, "");
  return srvBase === cfgBase && localServer.model.trim() === config.model.trim();
}

export function isStaleManagedLocalServer(response: PerceptionStatusResponse, localEndpoint: boolean): boolean {
  return Boolean(
    localEndpoint &&
    response.localServer?.managed &&
    response.localServer.state === "running" &&
    isSameLocalTarget(response.localServer, response.config),
  );
}

export function isServerTerminalFailure(server: PerceptionLocalServerStatus | undefined): boolean {
  if (!server) return false;
  return (
    server.state === "failed" || server.state === "stopped" || (server.state === "starting" && Boolean(server.error))
  );
}

export function dependencyPackageLabel(packageName: string | undefined, fallback = "torch"): string {
  const label = String(packageName || "")
    .replace(/(?:\[|[<>=!~]).*$/, "")
    .trim();
  return label || fallback;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error ?? "");
}
