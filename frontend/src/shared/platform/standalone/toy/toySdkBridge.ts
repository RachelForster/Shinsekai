/**
 * Safe Bilibili Toy container bridge (`window.toy`).
 * - Syncs lightweight progress checkpoints (character, prologue state, stats summary) via setCloudStorage.
 * - Strictly event-driven with cooldown debounce (never called inside setInterval/loops/mousemove).
 * - Handles error code 307044 with exponential backoff per Bilibili Toy rate-limit rules.
 */

export interface ToyCloudStoragePayload {
  v: 1;
  characterName: string;
  prologueCompleted: boolean;
  prologueStepId: string;
  statsSummary: Array<{ label: string; value: number; max?: number }>;
  updatedAtMs: number;
}

interface ToyContainerSdk {
  available?: () => boolean;
  getCloudStorage?: (options: {
    keyList?: string[];
    keys?: string[];
    success?: (res: unknown) => void;
    fail?: (err: unknown) => void;
  }) => Promise<unknown> | void;
  setCloudStorage?: (options: {
    KVDataList?: Array<{ key: string; value: string }>;
    data?: Record<string, string>;
    success?: () => void;
    fail?: (err: unknown) => void;
  }) => Promise<unknown> | void;
}

const TOY_CHECKPOINT_KEY = "shinsekai_checkpoint_v1";
const MIN_SYNC_INTERVAL_MS = 15_000;
const BASE_BACKOFF_MS = 5_000;
const MAX_BACKOFF_MS = 120_000;

export function getToySdk(): ToyContainerSdk | null {
  if (typeof window === "undefined") {
    return null;
  }
  const sdk = (window as Window & { toy?: ToyContainerSdk }).toy;
  if (!sdk || typeof sdk !== "object") {
    return null;
  }
  return sdk;
}

export function isToyContainerAvailable(): boolean {
  const sdk = getToySdk();
  if (!sdk) return false;
  if (typeof sdk.available === "function") {
    try {
      return Boolean(sdk.available());
    } catch {
      return false;
    }
  }
  return true;
}

export function isToyRateLimitError(error: unknown): boolean {
  if (!error) return false;
  if (typeof error === "string" || typeof error === "number") {
    return String(error).includes("307044");
  }
  if (typeof error === "object") {
    const obj = error as {
      code?: unknown;
      errCode?: unknown;
      statusCode?: unknown;
      message?: unknown;
      errMsg?: unknown;
    };
    return (
      String(obj.code ?? "") === "307044" ||
      String(obj.errCode ?? "") === "307044" ||
      String(obj.statusCode ?? "") === "307044" ||
      String(obj.message ?? "").includes("307044") ||
      String(obj.errMsg ?? "").includes("307044")
    );
  }
  return false;
}

export function computeRateLimitBackoffMs(retryAttempt: number): number {
  const exponent = Math.max(0, Math.min(6, retryAttempt));
  return Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** exponent);
}

export class ToyCloudCheckpointBridge {
  private lastWriteAtMs = 0;
  private blockedUntilMs = 0;
  private rateLimitFailures = 0;
  private pendingTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingPayload: ToyCloudStoragePayload | null = null;
  private pageHideBound = false;

  getBackoffState(): { blockedUntilMs: number; rateLimitFailures: number } {
    return {
      blockedUntilMs: this.blockedUntilMs,
      rateLimitFailures: this.rateLimitFailures,
    };
  }

  bindVisibilityFlush(buildPayload: () => ToyCloudStoragePayload | null): void {
    if (this.pageHideBound || typeof document === "undefined") {
      return;
    }
    this.pageHideBound = true;
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        const snapshot = buildPayload();
        if (snapshot) {
          this.scheduleCheckpointSync(snapshot, true);
        }
      }
    });
  }

  async loadCheckpoint(): Promise<ToyCloudStoragePayload | null> {
    const sdk = getToySdk();
    if (!sdk || !isToyContainerAvailable() || typeof sdk.getCloudStorage !== "function") {
      return null;
    }
    try {
      const rawRes = await new Promise<unknown>((resolve, reject) => {
        const maybePromise = sdk.getCloudStorage?.({
          keyList: [TOY_CHECKPOINT_KEY],
          keys: [TOY_CHECKPOINT_KEY],
          success: (res) => resolve(res),
          fail: (err) => reject(err),
        });
        if (maybePromise && typeof (maybePromise as Promise<unknown>).then === "function") {
          (maybePromise as Promise<unknown>).then(resolve, reject);
        }
      });

      const obj = rawRes as Record<string, unknown> | null;
      const list = Array.isArray(obj?.KVDataList) ? (obj.KVDataList as Array<{ key?: string; value?: string }>) : [];
      const fromList = list.find((item) => item?.key === TOY_CHECKPOINT_KEY)?.value;
      const fromMap = typeof obj?.[TOY_CHECKPOINT_KEY] === "string" ? (obj[TOY_CHECKPOINT_KEY] as string) : undefined;
      const jsonStr = fromList ?? fromMap;
      if (!jsonStr) return null;

      const parsed = JSON.parse(jsonStr) as Partial<ToyCloudStoragePayload>;
      if (parsed?.v !== 1 || typeof parsed.characterName !== "string") {
        return null;
      }
      return parsed as ToyCloudStoragePayload;
    } catch (error) {
      if (isToyRateLimitError(error)) {
        this.recordRateLimitFailure();
      }
      return null;
    }
  }

  scheduleCheckpointSync(payload: ToyCloudStoragePayload, immediateIfAllowed = false): void {
    const sdk = getToySdk();
    if (!sdk || !isToyContainerAvailable() || typeof sdk.setCloudStorage !== "function") {
      return;
    }
    this.pendingPayload = payload;
    if (this.pendingTimer !== null) {
      globalThis.clearTimeout(this.pendingTimer);
      this.pendingTimer = null;
    }

    const now = Date.now();
    const earliestAllowed = Math.max(this.lastWriteAtMs + MIN_SYNC_INTERVAL_MS, this.blockedUntilMs);
    const waitMs = immediateIfAllowed && now >= earliestAllowed ? 50 : Math.max(800, earliestAllowed - now);

    this.pendingTimer = globalThis.setTimeout(() => {
      this.pendingTimer = null;
      void this.flushPendingCheckpoint();
    }, waitMs);
  }

  async flushPendingCheckpoint(): Promise<boolean> {
    const payload = this.pendingPayload;
    const sdk = getToySdk();
    if (!payload || !sdk || !isToyContainerAvailable() || typeof sdk.setCloudStorage !== "function") {
      return false;
    }
    if (Date.now() < this.blockedUntilMs) {
      return false;
    }

    const encoded = JSON.stringify(payload);
    if (encoded.length > 3500) {
      return false;
    }

    try {
      this.lastWriteAtMs = Date.now();
      await new Promise<void>((resolve, reject) => {
        const maybePromise = sdk.setCloudStorage?.({
          KVDataList: [{ key: TOY_CHECKPOINT_KEY, value: encoded }],
          data: { [TOY_CHECKPOINT_KEY]: encoded },
          success: () => resolve(),
          fail: (err) => reject(err),
        });
        if (maybePromise && typeof (maybePromise as Promise<unknown>).then === "function") {
          (maybePromise as Promise<unknown>).then(() => resolve(), reject);
        }
      });
      this.rateLimitFailures = 0;
      this.blockedUntilMs = 0;
      this.pendingPayload = null;
      return true;
    } catch (error) {
      if (isToyRateLimitError(error)) {
        this.recordRateLimitFailure();
      }
      return false;
    }
  }

  recordRateLimitFailure(nowMs = Date.now()): number {
    const waitMs = computeRateLimitBackoffMs(this.rateLimitFailures);
    this.rateLimitFailures += 1;
    this.blockedUntilMs = nowMs + waitMs;
    return waitMs;
  }
}
