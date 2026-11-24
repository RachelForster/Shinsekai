import { useCallback, useEffect, useRef, useState } from "react";

export type AutoSavePhase = "idle" | "pending" | "saving" | "saved" | "error";

export interface AutoSaveContext {
  isSuperseded: () => boolean;
  resetKey: string;
}

export interface UseDebouncedAutoSaveOptions<TPayload> {
  baselineKey: string;
  buildPayload: () => TPayload;
  currentKey: string;
  debounceMs?: number;
  enabled: boolean;
  onError?: (error: unknown, context: AutoSaveContext) => void;
  onSave: (payload: TPayload, context: AutoSaveContext) => Promise<unknown>;
  rescheduleToken?: number;
  resetKey: string;
  validate?: (payload: TPayload) => string | null;
}

interface PendingAutoSave<TPayload> {
  compositeKey: string;
  onError?: (error: unknown, context: AutoSaveContext) => void;
  onSave: (payload: TPayload, context: AutoSaveContext) => Promise<unknown>;
  payload: TPayload;
  resetKey: string;
  useCapturedPayload?: boolean;
}

export function useDebouncedAutoSave<TPayload>({
  baselineKey,
  buildPayload,
  currentKey,
  debounceMs = 600,
  enabled,
  onError,
  onSave,
  rescheduleToken,
  resetKey,
  validate,
}: UseDebouncedAutoSaveOptions<TPayload>) {
  const [phase, setPhase] = useState<AutoSavePhase>("idle");
  const [errorMessage, setErrorMessage] = useState("");

  const buildPayloadRef = useRef(buildPayload);
  buildPayloadRef.current = buildPayload;
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const validateRef = useRef(validate);
  validateRef.current = validate;
  const latestResetKeyRef = useRef(resetKey);
  latestResetKeyRef.current = resetKey;
  const latestEnabledRef = useRef(enabled);
  latestEnabledRef.current = enabled;

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<PendingAutoSave<TPayload> | null>(null);
  const inFlightByKeyRef = useRef<Map<string, Promise<void>>>(new Map());
  const inFlightCompositeByKeyRef = useRef<Map<string, string>>(new Map());
  const queuedByKeyRef = useRef<Map<string, PendingAutoSave<TPayload>>>(new Map());
  const cancelledKeysRef = useRef<Set<string>>(new Set());
  const keyGenerationRef = useRef<Map<string, number>>(new Map());
  const failedKeyRef = useRef<string | null>(null);
  const failedMessageRef = useRef("");
  const lastSavedResetKeyRef = useRef<string | null>(null);
  const activeResetKeyRef = useRef(resetKey);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const bumpGeneration = useCallback((key: string) => {
    keyGenerationRef.current.set(key, (keyGenerationRef.current.get(key) ?? 0) + 1);
  }, []);

  const resolveSnapshotPayload = useCallback((snapshot: PendingAutoSave<TPayload>): TPayload | null => {
    if (
      !snapshot.useCapturedPayload &&
      mountedRef.current &&
      latestEnabledRef.current &&
      latestResetKeyRef.current === snapshot.resetKey
    ) {
      const freshPayload = buildPayloadRef.current();
      const validationError = validateRef.current ? validateRef.current(freshPayload) : null;
      if (validationError) {
        if (mountedRef.current && activeResetKeyRef.current === snapshot.resetKey) {
          setPhase("error");
          setErrorMessage(validationError);
        }
        return null;
      }
      return freshPayload;
    }
    return snapshot.payload;
  }, []);

  const executePending = useCallback(
    (initialSnapshot: PendingAutoSave<TPayload>): Promise<void> => {
      const key = initialSnapshot.resetKey;
      if (cancelledKeysRef.current.has(key)) {
        if (pendingRef.current?.resetKey === key) {
          pendingRef.current = null;
        }
        return Promise.resolve();
      }

      if (pendingRef.current?.compositeKey === initialSnapshot.compositeKey) {
        pendingRef.current = null;
      }

      const resolvedPayload = resolveSnapshotPayload(initialSnapshot);
      if (resolvedPayload === null) {
        return Promise.resolve();
      }
      const preparedSnapshot: PendingAutoSave<TPayload> = {
        ...initialSnapshot,
        payload: resolvedPayload,
        useCapturedPayload: true,
      };

      const existingFlight = inFlightByKeyRef.current.get(key);
      if (existingFlight) {
        queuedByKeyRef.current.set(key, preparedSnapshot);
        if (mountedRef.current && activeResetKeyRef.current === key) {
          setPhase("saving");
          setErrorMessage("");
        }
        return existingFlight;
      }

      if (mountedRef.current && activeResetKeyRef.current === key) {
        setPhase("saving");
        setErrorMessage("");
      }

      const runLoop = async (first: PendingAutoSave<TPayload>) => {
        let current: PendingAutoSave<TPayload> | undefined = first;
        while (current) {
          if (cancelledKeysRef.current.has(key)) {
            queuedByKeyRef.current.delete(key);
            break;
          }
          const runGen = keyGenerationRef.current.get(key) ?? 0;
          const isSuperseded = () =>
            cancelledKeysRef.current.has(key) || (keyGenerationRef.current.get(key) ?? 0) !== runGen;
          inFlightCompositeByKeyRef.current.set(key, current.compositeKey);
          try {
            await current.onSave(current.payload, { isSuperseded, resetKey: key });
            if (failedKeyRef.current === current.compositeKey) {
              failedKeyRef.current = null;
              failedMessageRef.current = "";
            }
            const superseded = isSuperseded();
            const nextQueued = queuedByKeyRef.current.get(key);
            if (!superseded) {
              lastSavedResetKeyRef.current = key;
              if (
                !nextQueued &&
                mountedRef.current &&
                activeResetKeyRef.current === key &&
                timerRef.current === null &&
                pendingRef.current === null
              ) {
                setPhase("saved");
                setErrorMessage("");
              }
            }
          } catch (error: unknown) {
            const superseded = isSuperseded();
            const nextQueued = queuedByKeyRef.current.get(key);
            if (!superseded && !nextQueued) {
              const message = error instanceof Error ? error.message : String(error ?? "");
              failedKeyRef.current = current.compositeKey;
              failedMessageRef.current = message;
              if (mountedRef.current && activeResetKeyRef.current === key && timerRef.current === null) {
                setPhase("error");
                setErrorMessage(message);
              }
              current.onError?.(error, { isSuperseded, resetKey: key });
            }
          }
          const next = queuedByKeyRef.current.get(key);
          queuedByKeyRef.current.delete(key);
          current = next && !cancelledKeysRef.current.has(key) ? next : undefined;
        }
      };

      const flightPromise = runLoop(preparedSnapshot).finally(() => {
        inFlightByKeyRef.current.delete(key);
        inFlightCompositeByKeyRef.current.delete(key);
        if (activeResetKeyRef.current !== key) {
          cancelledKeysRef.current.delete(key);
        }
      });
      inFlightByKeyRef.current.set(key, flightPromise);
      return flightPromise;
    },
    [resolveSnapshotPayload],
  );

  const flush = useCallback(() => {
    clearTimer();
    const pending = pendingRef.current;
    if (!pending || cancelledKeysRef.current.has(pending.resetKey)) {
      pendingRef.current = null;
      return;
    }
    void executePending(pending);
  }, [clearTimer, executePending]);

  const discardPending = useCallback(
    (targetResetKey?: string): Promise<void> => {
      clearTimer();
      const key = targetResetKey ?? activeResetKeyRef.current;
      if (pendingRef.current?.resetKey === key) {
        pendingRef.current = null;
      }
      queuedByKeyRef.current.delete(key);
      if (failedKeyRef.current?.startsWith(`${key}::`)) {
        failedKeyRef.current = null;
        failedMessageRef.current = "";
      }
      bumpGeneration(key);
      if (mountedRef.current && activeResetKeyRef.current === key) {
        setPhase("idle");
        setErrorMessage("");
      }
      const inFlight = inFlightByKeyRef.current.get(key);
      return inFlight ? inFlight.catch(() => undefined) : Promise.resolve();
    },
    [bumpGeneration, clearTimer],
  );

  const cancel = useCallback(
    (targetResetKey?: string): Promise<void> => {
      clearTimer();
      const key = targetResetKey ?? activeResetKeyRef.current;
      cancelledKeysRef.current.add(key);
      if (pendingRef.current?.resetKey === key) {
        pendingRef.current = null;
      }
      queuedByKeyRef.current.delete(key);
      if (failedKeyRef.current?.startsWith(`${key}::`)) {
        failedKeyRef.current = null;
        failedMessageRef.current = "";
      }
      bumpGeneration(key);
      if (mountedRef.current && activeResetKeyRef.current === key) {
        setPhase("idle");
        setErrorMessage("");
      }
      const inFlight = inFlightByKeyRef.current.get(key);
      return inFlight ? inFlight.catch(() => undefined) : Promise.resolve();
    },
    [bumpGeneration, clearTimer],
  );

  useEffect(() => {
    const previousKey = activeResetKeyRef.current;
    if (previousKey !== resetKey) {
      clearTimer();
      const pending = pendingRef.current;
      pendingRef.current = null;
      const wasCancelled = cancelledKeysRef.current.has(previousKey);
      if (pending && pending.resetKey === previousKey && !wasCancelled) {
        void executePending({ ...pending, useCapturedPayload: true });
      }
      if (wasCancelled && !inFlightByKeyRef.current.has(previousKey)) {
        cancelledKeysRef.current.delete(previousKey);
      }
      cancelledKeysRef.current.delete(resetKey);
      activeResetKeyRef.current = resetKey;
      failedKeyRef.current = null;
      failedMessageRef.current = "";
      setPhase(inFlightByKeyRef.current.has(resetKey) ? "saving" : "idle");
      setErrorMessage("");
    }
  }, [clearTimer, executePending, resetKey]);

  useEffect(() => {
    if (!enabled) {
      clearTimer();
      pendingRef.current = null;
      failedKeyRef.current = null;
      failedMessageRef.current = "";
      setPhase(inFlightByKeyRef.current.has(resetKey) ? "saving" : "idle");
      setErrorMessage("");
      return;
    }

    if (cancelledKeysRef.current.has(resetKey)) {
      clearTimer();
      pendingRef.current = null;
      return;
    }

    if (currentKey === baselineKey) {
      clearTimer();
      pendingRef.current = null;
      queuedByKeyRef.current.delete(resetKey);
      failedKeyRef.current = null;
      failedMessageRef.current = "";
      if (!inFlightByKeyRef.current.has(resetKey)) {
        setPhase(lastSavedResetKeyRef.current === resetKey ? "saved" : "idle");
        setErrorMessage("");
      }
      return;
    }

    const payload = buildPayloadRef.current();
    const validationError = validateRef.current ? validateRef.current(payload) : null;
    if (validationError) {
      clearTimer();
      pendingRef.current = null;
      queuedByKeyRef.current.delete(resetKey);
      setPhase("error");
      setErrorMessage(validationError);
      return;
    }

    const compositeKey = `${resetKey}::${currentKey}`;
    if (failedKeyRef.current === compositeKey) {
      clearTimer();
      pendingRef.current = null;
      queuedByKeyRef.current.delete(resetKey);
      if (inFlightByKeyRef.current.has(resetKey)) {
        setPhase("saving");
        setErrorMessage("");
      } else {
        setPhase("error");
        setErrorMessage(failedMessageRef.current);
      }
      return;
    }

    if (inFlightCompositeByKeyRef.current.get(resetKey) === compositeKey) {
      clearTimer();
      pendingRef.current = null;
      queuedByKeyRef.current.delete(resetKey);
      setPhase("saving");
      setErrorMessage("");
      return;
    }

    clearTimer();
    const snapshot: PendingAutoSave<TPayload> = {
      compositeKey,
      onError: onErrorRef.current,
      onSave: onSaveRef.current,
      payload,
      resetKey,
    };
    pendingRef.current = snapshot;
    setPhase(inFlightByKeyRef.current.has(resetKey) ? "saving" : "pending");
    setErrorMessage("");

    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      if (pendingRef.current?.compositeKey === compositeKey) {
        void executePending(pendingRef.current);
      }
    }, debounceMs);
  }, [baselineKey, clearTimer, currentKey, debounceMs, enabled, executePending, rescheduleToken, resetKey]);

  useEffect(() => {
    const handleBeforeUnload = () => {
      flush();
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      flush();
    };
  }, [flush]);

  const retry = useCallback(() => {
    if (!enabled || currentKey === baselineKey || cancelledKeysRef.current.has(resetKey)) {
      return;
    }
    const payload = buildPayloadRef.current();
    const validationError = validateRef.current ? validateRef.current(payload) : null;
    if (validationError) {
      setPhase("error");
      setErrorMessage(validationError);
      return;
    }
    clearTimer();
    failedKeyRef.current = null;
    failedMessageRef.current = "";
    void executePending({
      compositeKey: `${resetKey}::${currentKey}`,
      onError: onErrorRef.current,
      onSave: onSaveRef.current,
      payload,
      resetKey,
      useCapturedPayload: true,
    });
  }, [baselineKey, clearTimer, currentKey, enabled, executePending, resetKey]);

  return {
    cancel,
    discardPending,
    errorMessage,
    flush,
    phase,
    retry,
  };
}
