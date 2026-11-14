import {
  isDesktopBridgeRestarting,
  isTauriDesktop,
  waitForDesktopBridgeRestart,
  writeDesktopRestartDebugLog,
} from "../desktop/desktopApi";
import { PlatformRequestError } from "./errors";
import type { TaskProgressOptions, TaskSnapshot } from "./slices/taskTypes";

export interface HttpTransport {
  apiBase: string;
  authToken: () => string;
  bridgeUrl: (path: string) => string;
  encodePath: (value: string) => string;
  exportPackage: (resource: string, name: string) => Promise<string>;
  isFileList: (items: File[] | string[]) => items is File[];
  openBridgeWindow: (path: string) => void;
  requestJson: <T>(path: string, init?: RequestInit) => Promise<T>;
  uploadFiles: <T>(path: string, files: File[]) => Promise<T>;
  waitForTask: <TResult>(
    initialTask: TaskSnapshot<TResult>,
    options?: TaskProgressOptions<TResult>,
  ) => Promise<TResult>;
}

const bridgeAuthTokens = new Map<string, string>();

function normalizedBaseUrl(baseUrl: string) {
  return baseUrl.replace(/\/$/, "");
}

function rememberBridgeAuthToken(baseUrl: string, authToken?: string) {
  const token = authToken?.trim() ?? "";
  const key = normalizedBaseUrl(baseUrl);
  if (token) {
    bridgeAuthTokens.set(key, token);
  } else {
    bridgeAuthTokens.delete(key);
  }
}

function bridgeAuthToken(baseUrl: string) {
  return bridgeAuthTokens.get(normalizedBaseUrl(baseUrl)) ?? "";
}

function bridgeAuthHeaders(baseUrl: string): Record<string, string> {
  const token = bridgeAuthToken(baseUrl);
  return token ? { "X-Shinsekai-Bridge-Token": token } : {};
}

function headersRecord(headers?: HeadersInit): Record<string, string> {
  if (!headers) {
    return {};
  }
  if (typeof Headers !== "undefined" && headers instanceof Headers) {
    const result: Record<string, string> = {};
    headers.forEach((value, key) => {
      result[key] = value;
    });
    return result;
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers.map(([key, value]) => [key, value]));
  }
  return { ...(headers as Record<string, string>) };
}

function appendBridgeAuthQuery(baseUrl: string, pathOrUrl: string) {
  const token = bridgeAuthToken(baseUrl);
  if (!token) {
    return pathOrUrl;
  }
  const separator = pathOrUrl.includes("?") ? "&" : "?";
  return `${pathOrUrl}${separator}shinsekai_bridge_token=${encodeURIComponent(token)}`;
}

function bridgeUrl(baseUrl: string, path: string) {
  const base = new URL(baseUrl);
  const url = new URL(appendBridgeAuthQuery(baseUrl, path), base);
  if (url.origin !== base.origin) {
    throw new Error("Bridge URL must stay on the active bridge origin");
  }
  return url.toString();
}

function openBridgeWindow(apiBase: string, path: string) {
  const url = bridgeUrl(apiBase, path);
  window.open(url, "_blank", "noopener,noreferrer");
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isDesktopRestarting() {
  return typeof window !== "undefined" && window.__SHINSEKAI_RESTARTING__ === true;
}

function errorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function waitForRestartExit(): Promise<never> {
  return new Promise(() => {});
}

function sanitizeRestartLogUrl(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return url;
  }
}

function logSuppressedRestartError(method: string, url: string, error: unknown) {
  void writeDesktopRestartDebugLog(
    `httpPlatform suppressed restart disconnect method=${method} url=${sanitizeRestartLogUrl(url)} error=${errorMessage(
      error,
    )}`,
  );
}

function logThrownBridgeError(method: string, url: string, error: unknown) {
  void writeDesktopRestartDebugLog(
    `httpPlatform throwing bridge error method=${method} url=${sanitizeRestartLogUrl(url)} restarting=${isDesktopRestarting()} error=${errorMessage(
      error,
    )}`,
  );
}

function logBridgeRestartRetry(method: string, url: string, error: unknown) {
  void writeDesktopRestartDebugLog(
    `httpPlatform waiting for bridge restart method=${method} url=${sanitizeRestartLogUrl(url)} error=${errorMessage(
      error,
    )}`,
  );
}

function isTransientBridgeError(error: unknown) {
  const message = errorMessage(error);
  return /127\.0\.0\.1|localhost|connection refused|could not connect|failed to fetch|network/i.test(message);
}

async function fetchWithStartupRetry(url: string, init: RequestInit): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const retryable = method === "GET" || method === "HEAD";
  const maxRetryAttempts = retryable ? 15 : 1;
  let lastError: unknown;
  let attempt = 0;
  let waitedForBridgeRestart = false;
  for (;;) {
    try {
      return await fetch(url, init);
    } catch (error) {
      lastError = error;
      if (isDesktopBridgeRestarting() && isTransientBridgeError(error) && !waitedForBridgeRestart) {
        waitedForBridgeRestart = true;
        logBridgeRestartRetry(method, url, error);
        await waitForDesktopBridgeRestart();
        continue;
      }
      if (isDesktopRestarting() && isTransientBridgeError(error)) {
        logSuppressedRestartError(method, url, error);
        return waitForRestartExit();
      }
      if (!retryable || !isTransientBridgeError(error)) {
        if (isTransientBridgeError(error)) {
          logThrownBridgeError(method, url, error);
        }
        throw error;
      }
      if (attempt + 1 >= maxRetryAttempts) {
        break;
      }
      attempt += 1;
      await delay(200 + attempt * 150);
    }
  }
  if (isTransientBridgeError(lastError)) {
    logThrownBridgeError(method, url, lastError);
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const requestHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...bridgeAuthHeaders(baseUrl),
    ...headersRecord(init?.headers),
  };
  const requestInit: RequestInit = {
    ...init,
    headers: requestHeaders,
  };
  const response = await fetchWithStartupRetry(`${baseUrl}${path}`, requestInit);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data?.error === "string" ? data.error : `${response.status} ${response.statusText}`;
    const errorCode = typeof data?.errorCode === "string" ? data.errorCode : undefined;
    throw new PlatformRequestError(message, response.status, errorCode);
  }
  return data as T;
}

async function requestForm<T>(baseUrl: string, path: string, formData: FormData): Promise<T> {
  const url = `${baseUrl}${path}`;
  const headers = bridgeAuthHeaders(baseUrl);
  const init: RequestInit = {
    body: formData,
    method: "POST",
  };
  if (Object.keys(headers).length) {
    init.headers = headers;
  }
  const response = await fetch(url, init).catch(async (error) => {
    if (isDesktopBridgeRestarting() && isTransientBridgeError(error)) {
      logBridgeRestartRetry("POST", url, error);
      await waitForDesktopBridgeRestart();
      return fetch(url, init);
    }
    if (isDesktopRestarting() && isTransientBridgeError(error)) {
      logSuppressedRestartError("POST", url, error);
      return waitForRestartExit();
    }
    throw error;
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data?.error === "string" ? data.error : `${response.status} ${response.statusText}`;
    const errorCode = typeof data?.errorCode === "string" ? data.errorCode : undefined;
    throw new PlatformRequestError(message, response.status, errorCode);
  }
  return data as T;
}

function encodePath(value: string) {
  return encodeURIComponent(value);
}

function isFileList(items: File[] | string[]): items is File[] {
  return items.some((item) => item instanceof File);
}

function uploadFiles<T>(apiBase: string, path: string, files: File[]): Promise<T> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file, file.name);
  }
  return requestForm<T>(apiBase, path, formData);
}

function openDownload(apiBase: string, path: string) {
  openBridgeWindow(apiBase, `/api/download?path=${encodeURIComponent(path)}`);
}

async function exportPackage(apiBase: string, resource: string, name: string) {
  const openFolder = isTauriDesktop();
  const result = await requestJson<{ downloadUrl: string; path: string; folderOpened?: boolean }>(
    apiBase,
    `/api/${resource}/export`,
    {
      body: JSON.stringify({ name, ...(openFolder ? { openFolder: true } : {}) }),
      method: "POST",
    },
  );
  if (!openFolder || result.folderOpened !== true) {
    openDownload(apiBase, result.path);
  }
  return result.path;
}

function isTaskRunning(task: TaskSnapshot) {
  return task.status === "queued" || task.status === "running";
}

async function waitForTask<TResult>(
  apiBase: string,
  initialTask: TaskSnapshot<TResult>,
  options?: TaskProgressOptions<TResult>,
): Promise<TResult> {
  let task = initialTask;
  options?.onTaskUpdate?.(task);

  while (isTaskRunning(task)) {
    await delay(450);
    task = await requestJson<TaskSnapshot<TResult>>(apiBase, `/api/tasks/${encodePath(task.id)}`);
    options?.onTaskUpdate?.(task);
  }

  if (task.status === "failed") {
    throw new Error(task.error || task.message || "任务失败。");
  }
  if (task.status === "cancelled") {
    const error = new Error(task.message || "任务已取消。");
    error.name = "TaskCancelledError";
    throw error;
  }
  if (!task.result) {
    throw new Error(task.message || "任务完成但没有返回结果。");
  }
  return task.result;
}

export function createHttpTransport(baseUrl: string, authToken = ""): HttpTransport {
  const apiBase = normalizedBaseUrl(baseUrl);
  rememberBridgeAuthToken(apiBase, authToken);

  return {
    apiBase,
    authToken: () => bridgeAuthToken(apiBase),
    bridgeUrl: (path) => bridgeUrl(apiBase, path),
    encodePath,
    exportPackage: (resource, name) => exportPackage(apiBase, resource, name),
    isFileList,
    openBridgeWindow: (path) => openBridgeWindow(apiBase, path),
    requestJson: (path, init) => requestJson(apiBase, path, init),
    uploadFiles: (path, files) => uploadFiles(apiBase, path, files),
    waitForTask: (initialTask, options) => waitForTask(apiBase, initialTask, options),
  };
}
