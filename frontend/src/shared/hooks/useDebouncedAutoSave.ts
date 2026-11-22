import { useCallback, useEffect, useRef, useState } from "react";

export type AutoSavePhase = "idle" | "pending" | "saving" | "saved" | "error";

export interface UseDebouncedAutoSaveOptions<TPayload> {
  baselineKey: string;
  buildPayload: () => TPayload;
  currentKey: string;
  debounceMs?: number;
  enabled: boolean;
  onError?: (error: unknown) => void;
  onSave: (payload: TPayload) => Promise<unknown>;
  resetKey: string;
  validate?: (payload: TPayload) => string | null;
}

interface PendingAutoSave<TPayload> {
  compositeKey: string;
  onError?: (error: unknown) => void;
  onSave: (payload: TPayload) => Promise<unknown>;
  payload: TPayload;
  resetKey: string;
}

export function useDebouncedAutoSave<TPayload>({
  baselineKey,
  buildPayload,
  currentKey,
  debounceMs = 600,
  enabled,
  onError,
  onSave,
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

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<PendingAutoSave<TPayload> | null>(null);
  const inFlightKeyRef = useRef<string | null>(null);
  const failedKeyRef = useRef<string | null>(null);
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

  const executePending = useCallback((snapshot: PendingAutoSave<TPayload>) => {
    pendingRef.current = null;
    inFlightKeyRef.current = snapshot.compositeKey;
    if (mountedRef.current && activeResetKeyRef.current === snapshot.resetKey) {
      setPhase("saving");
      setErrorMessage("");
    }
    return snapshot
      .onSave(snapshot.payload)
      .then(() => {
        if (inFlightKeyRef.current === snapshot.compositeKey) {
          inFlightKeyRef.current = null;
        }
        if (failedKeyRef.current === snapshot.compositeKey) {
          failedKeyRef.current = null;
        }
        lastSavedResetKeyRef.current = snapshot.resetKey;
        if (mountedRef.current && activeResetKeyRef.current === snapshot.resetKey && timerRef.current === null) {
          setPhase("saved");
          setErrorMessage("");
        }
      })
      .catch((error: unknown) => {
        if (inFlightKeyRef.current === snapshot.compositeKey) {
          inFlightKeyRef.current = null;
        }
        failedKeyRef.current = snapshot.compositeKey;
        if (mountedRef.current && activeResetKeyRef.current === snapshot.resetKey) {
          setPhase("error");
          setErrorMessage(error instanceof Error ? error.message : String(error ?? ""));
        }
        snapshot.onError?.(error);
      });
  }, []);

  const flush = useCallback(() => {
    clearTimer();
    const pending = pendingRef.current;
    if (!pending) {
      return;
    }
    void executePending(pending);
  }, [clearTimer, executePending]);

  useEffect(() => {
    if (activeResetKeyRef.current !== resetKey) {
      if (pendingRef.current) {
        clearTimer();
        void executePending(pendingRef.current);
      } else {
        clearTimer();
      }
      activeResetKeyRef.current = resetKey;
      failedKeyRef.current = null;
      setPhase("idle");
      setErrorMessage("");
    }
  }, [clearTimer, executePending, resetKey]);

  useEffect(() => {
    if (!enabled) {
      clearTimer();
      pendingRef.current = null;
      failedKeyRef.current = null;
      setPhase("idle");
      setErrorMessage("");
      return;
    }

    if (currentKey === baselineKey) {
      clearTimer();
      pendingRef.current = null;
      failedKeyRef.current = null;
      if (inFlightKeyRef.current === null) {
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
      setPhase("error");
      setErrorMessage(validationError);
      return;
    }

    const compositeKey = `${resetKey}::${currentKey}`;
    if (inFlightKeyRef.current === compositeKey || failedKeyRef.current === compositeKey) {
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
    setPhase(inFlightKeyRef.current ? "saving" : "pending");
    setErrorMessage("");

    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      if (pendingRef.current?.compositeKey === compositeKey) {
        void executePending(pendingRef.current);
      }
    }, debounceMs);
  }, [baselineKey, clearTimer, currentKey, debounceMs, enabled, executePending, resetKey]);

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
    if (!enabled || currentKey === baselineKey) {
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
    void executePending({
      compositeKey: `${resetKey}::${currentKey}`,
      onError: onErrorRef.current,
      onSave: onSaveRef.current,
      payload,
      resetKey,
    });
  }, [baselineKey, clearTimer, currentKey, enabled, executePending, resetKey]);

  return {
    errorMessage,
    flush,
    phase,
    retry,
  };
}
