import {
  cancelTauriStandaloneHttp,
  hasTauriNativeHttp,
  invokeTauriStandaloneHttp,
  isAbortTauriHttpError,
  isUnknownTauriCommandError,
  markTauriNativeHttpUnsupported,
  type TauriStandaloneHttpResponse,
} from "../../../desktop/desktopApi";

export interface StandaloneHttpRequest {
  url: string;
  method?: string;
  headers?: Record<string, string>;
  body?: string | Uint8Array;
  timeoutMs?: number;
  signal?: AbortSignal;
}

export interface StandaloneHttpResponse {
  status: number;
  ok: boolean;
  headers: Record<string, string>;
  body: Uint8Array;
  text: () => string;
  json: <T = unknown>() => T;
}

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder("utf-8", { fatal: false });
let nativeRequestSeq = 0;

function nextNativeRequestId(): string {
  nativeRequestSeq += 1;
  return `tauri-http-${Date.now()}-${nativeRequestSeq}`;
}

function createAbortError(): Error {
  if (typeof DOMException === "function") {
    return new DOMException("The operation was aborted.", "AbortError");
  }
  const error = new Error("The operation was aborted.");
  error.name = "AbortError";
  return error;
}

export function bytesToBase64(bytes: Uint8Array): string {
  const chunkSize = 0x4000;
  const parts: string[] = [];
  for (let i = 0; i < bytes.byteLength; i += chunkSize) {
    const slice = bytes.subarray(i, Math.min(i + chunkSize, bytes.byteLength));
    let chunkStr = "";
    for (let j = 0; j < slice.length; j += 1) {
      chunkStr += String.fromCharCode(slice[j]);
    }
    parts.push(chunkStr);
  }
  if (typeof btoa === "function") {
    return btoa(parts.join(""));
  }
  throw new Error("Base64 encoding is unavailable in this environment.");
}

export function base64ToBytes(b64: string): Uint8Array {
  if (!b64) return new Uint8Array(0);
  if (typeof atob === "function") {
    const binary = atob(b64);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      out[i] = binary.charCodeAt(i);
    }
    return out;
  }
  throw new Error("Base64 decoding is unavailable in this environment.");
}

function normalizeHeadersMap(headers: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  headers.forEach((val, key) => {
    out[key.toLowerCase()] = val;
  });
  return out;
}

function buildResponse(status: number, headers: Record<string, string>, body: Uint8Array): StandaloneHttpResponse {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers,
    body,
    text: () => textDecoder.decode(body),
    json: <T = unknown>() => JSON.parse(textDecoder.decode(body)) as T,
  };
}

export async function standaloneHttpRequest(request: StandaloneHttpRequest): Promise<StandaloneHttpResponse> {
  const method = (request.method ?? "GET").toUpperCase();
  const timeoutMs = request.timeoutMs ?? 60_000;

  if (request.signal?.aborted) {
    throw createAbortError();
  }

  if (hasTauriNativeHttp()) {
    let bodyBase64: string | undefined;
    if (typeof request.body === "string") {
      bodyBase64 = bytesToBase64(textEncoder.encode(request.body));
    } else if (request.body instanceof Uint8Array) {
      bodyBase64 = bytesToBase64(request.body);
    }

    const requestId = nextNativeRequestId();
    let timedOut = false;
    let settled = false;
    let onAbort: (() => void) | null = null;
    let timerId: ReturnType<typeof globalThis.setTimeout> | null = null;

    try {
      const nativeResp = await new Promise<TauriStandaloneHttpResponse>((resolve, reject) => {
        onAbort = () => {
          if (settled) return;
          settled = true;
          void cancelTauriStandaloneHttp(requestId);
          reject(createAbortError());
        };
        request.signal?.addEventListener("abort", onAbort, { once: true });

        if (timeoutMs > 0) {
          timerId = globalThis.setTimeout(() => {
            if (settled) return;
            settled = true;
            timedOut = true;
            void cancelTauriStandaloneHttp(requestId);
            reject(new Error(`请求超时 (${timeoutMs}ms): ${request.url}`));
          }, timeoutMs);
        }

        invokeTauriStandaloneHttp({
          requestId,
          url: request.url,
          method,
          headers: request.headers,
          bodyBase64,
          timeoutMs,
        }).then(
          (resp) => {
            if (settled) return;
            settled = true;
            resolve(resp);
          },
          (err) => {
            if (settled) return;
            settled = true;
            if (request.signal?.aborted || isAbortTauriHttpError(err)) {
              reject(createAbortError());
              return;
            }
            reject(err);
          },
        );
      });
      const normalizedHeaders: Record<string, string> = {};
      for (const [k, v] of Object.entries(nativeResp.headers ?? {})) {
        normalizedHeaders[k.toLowerCase()] = v;
      }
      return buildResponse(nativeResp.status, normalizedHeaders, base64ToBytes(nativeResp.bodyBase64 ?? ""));
    } catch (error) {
      if (timedOut) {
        throw error;
      }
      if (request.signal?.aborted || isAbortTauriHttpError(error)) {
        throw createAbortError();
      }
      if (!isUnknownTauriCommandError(error)) {
        throw error;
      }
      // Fall back to standard fetch when running inside a Tauri shell without standalone_http_request registered.
      markTauriNativeHttpUnsupported();
    } finally {
      if (timerId !== null) {
        globalThis.clearTimeout(timerId);
      }
      if (onAbort) {
        request.signal?.removeEventListener("abort", onAbort);
      }
    }
  }

  const controller = new AbortController();
  let timedOut = false;
  const timerId =
    timeoutMs > 0
      ? globalThis.setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, timeoutMs)
      : null;

  const onExternalAbort = () => controller.abort();
  request.signal?.addEventListener("abort", onExternalAbort, { once: true });

  try {
    let fetchBody: BodyInit | undefined;
    if (typeof request.body === "string") {
      fetchBody = request.body;
    } else if (request.body instanceof Uint8Array) {
      const safeCopy = new Uint8Array(request.body.byteLength);
      safeCopy.set(request.body);
      fetchBody = safeCopy;
    }

    const resp = await fetch(request.url, {
      method,
      headers: request.headers,
      body: method === "GET" || method === "HEAD" ? undefined : fetchBody,
      signal: controller.signal,
    });
    const bytes = new Uint8Array(await resp.arrayBuffer());
    return buildResponse(resp.status, normalizeHeadersMap(resp.headers), bytes);
  } catch (error) {
    if (timedOut) {
      throw new Error(`请求超时 (${timeoutMs}ms): ${request.url}`);
    }
    throw error;
  } finally {
    if (timerId !== null) {
      globalThis.clearTimeout(timerId);
    }
    request.signal?.removeEventListener("abort", onExternalAbort);
  }
}

export async function standaloneHttpJson<T = unknown>(
  request: StandaloneHttpRequest,
): Promise<{ status: number; data: T }> {
  const resp = await standaloneHttpRequest(request);
  const rawText = resp.text();
  let parsed: unknown = null;
  try {
    parsed = rawText ? JSON.parse(rawText) : {};
  } catch {
    parsed = { rawText };
  }
  if (!resp.ok) {
    const obj = parsed as Record<string, unknown> | null;
    const errObj = obj?.error as Record<string, unknown> | string | undefined;
    const message =
      (typeof errObj === "object" && errObj && typeof errObj.message === "string" && errObj.message) ||
      (typeof errObj === "string" && errObj) ||
      (typeof obj?.message === "string" && obj.message) ||
      `HTTP ${resp.status}: ${rawText.slice(0, 240)}`;
    throw new Error(message);
  }
  return { status: resp.status, data: parsed as T };
}

export type StandaloneHttpClient = typeof standaloneHttpRequest;
