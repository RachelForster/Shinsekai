import { useCallback, useEffect, useRef, useState } from "react";

import { installMissingRuntimeDependency } from "../../../entities/chat/repository";
import { downloadModelAsset } from "../../../entities/model-assets/repository";
import { getPerceptionStatus, startPerceptionLocalServer } from "../../../entities/perception/repository";
import { DEFAULT_PERCEPTION_MODEL } from "../../../shared/platform/perceptionModel";
import type {
  ModelAssetRef,
  PerceptionHealthProbe,
  PerceptionLocalServerStatus,
  PerceptionSetupStatus,
  PerceptionStatusResponse,
  TaskSnapshot,
} from "../../../shared/platform/types";

export type ScreenSharePreflightPhase =
  | "idle"
  | "checking"
  | "setup_needed"
  | "installing"
  | "starting"
  | "ready"
  | "error";

export type ScreenSharePreflightErrorKind =
  | "model_mismatch"
  | "unreachable"
  | "server_failed"
  | "setup_error"
  | "missing_gguf"
  | "unknown";

export interface UseScreenSharePreflightOptions {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStartSharing: () => Promise<void> | void;
  screenSharing: boolean;
  screenShareStarting: boolean;
  sessionClosed: boolean;
}

const AUTO_LAUNCH_GESTURE_WINDOW_MS = 4000;
const POLL_INTERVAL_MS = 900;
const MAX_CONSECUTIVE_POLL_ERRORS = 3;
const PERCEPTION_VLM_ASSET: ModelAssetRef = { assetId: "perception.vlm" };
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

function isPerceptionServiceReady(response: PerceptionStatusResponse, localEndpoint: boolean): boolean {
  if (response.health !== undefined) {
    return Boolean(response.health.ok && response.health.modelPresent !== false);
  }
  return Boolean(
    localEndpoint && (response.localServer?.state === "running" || response.localServer?.state === "external_running"),
  );
}

function isSameLocalTarget(
  localServer: PerceptionLocalServerStatus | undefined,
  config: PerceptionStatusResponse["config"] | undefined,
): boolean {
  if (!localServer || !config) return false;
  const srvBase = localServer.baseUrl.trim().replace(/\/+$/, "");
  const cfgBase = config.baseUrl.trim().replace(/\/+$/, "");
  return srvBase === cfgBase && localServer.model.trim() === config.model.trim();
}

function dependencyPackageLabel(packageName: string | undefined, fallback = "torch"): string {
  const label = String(packageName || "")
    .replace(/(?:\[|[<>=!~]).*$/, "")
    .trim();
  return label || fallback;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error ?? "");
}

function isServerTerminalFailure(server: PerceptionLocalServerStatus | undefined): boolean {
  if (!server) return false;
  return (
    server.state === "failed" || server.state === "stopped" || (server.state === "starting" && Boolean(server.error))
  );
}

export function useScreenSharePreflight({
  open,
  onOpenChange,
  onStartSharing,
  screenSharing,
  screenShareStarting,
  sessionClosed,
}: UseScreenSharePreflightOptions) {
  const [phase, setPhase] = useState<ScreenSharePreflightPhase>("idle");
  const [status, setStatus] = useState<PerceptionStatusResponse | null>(null);
  const [localServer, setLocalServer] = useState<PerceptionLocalServerStatus | null>(null);
  const [setup, setSetup] = useState<PerceptionSetupStatus | null>(null);
  const [health, setHealth] = useState<PerceptionHealthProbe | null>(null);
  const [setupTask, setSetupTask] = useState<TaskSnapshot | null>(null);
  const [installingPackage, setInstallingPackage] = useState<string>();
  const [errorKind, setErrorKind] = useState<ScreenSharePreflightErrorKind | null>(null);
  const [errorDetail, setErrorDetail] = useState("");

  const runTokenRef = useRef(0);
  const pollTimerRef = useRef<number>(0);

  const onOpenChangeRef = useRef(onOpenChange);
  onOpenChangeRef.current = onOpenChange;
  const onStartSharingRef = useRef(onStartSharing);
  onStartSharingRef.current = onStartSharing;
  const flagsRef = useRef({ screenSharing, screenShareStarting, sessionClosed });
  flagsRef.current = { screenSharing, screenShareStarting, sessionClosed };

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = 0;
    }
  }, []);

  const failWith = useCallback((kind: ScreenSharePreflightErrorKind, detail = "") => {
    setErrorKind(kind);
    setErrorDetail(detail);
    setPhase("error");
  }, []);

  const applyStatusResponse = useCallback((response: PerceptionStatusResponse, includeHealth = false) => {
    setStatus(response);
    if (response.localServer || includeHealth) setLocalServer(response.localServer ?? null);
    if (response.setup || includeHealth) setSetup(response.setup ?? null);
    if (includeHealth) setHealth(response.health ?? null);
  }, []);

  const resetTransientState = useCallback(() => {
    setPhase("idle");
    setStatus(null);
    setLocalServer(null);
    setSetup(null);
    setHealth(null);
    setSetupTask(null);
    setInstallingPackage(undefined);
    setErrorKind(null);
    setErrorDetail("");
  }, []);

  const close = useCallback(() => {
    runTokenRef.current += 1;
    clearPollTimer();
    resetTransientState();
    onOpenChangeRef.current(false);
  }, [clearPollTimer, resetTransientState]);

  const schedulePoll = useCallback(
    (token: number, consecutiveErrors: number) => {
      clearPollTimer();
      pollTimerRef.current = window.setTimeout(() => {
        pollTimerRef.current = 0;
        if (runTokenRef.current !== token) return;
        void (async () => {
          try {
            const response = await getPerceptionStatus({ probe: false });
            if (runTokenRef.current !== token) return;
            applyStatusResponse(response);
            const srv = response.localServer;
            if (srv?.state === "running" || srv?.state === "external_running") {
              setPhase("ready");
              return;
            }
            if (isServerTerminalFailure(srv)) {
              failWith("server_failed", srv?.error || "");
              return;
            }
            schedulePoll(token, 0);
          } catch (error) {
            if (runTokenRef.current !== token) return;
            const nextErrors = consecutiveErrors + 1;
            if (nextErrors < MAX_CONSECUTIVE_POLL_ERRORS) {
              schedulePoll(token, nextErrors);
              return;
            }
            failWith("unknown", errorMessage(error));
          }
        })();
      }, POLL_INTERVAL_MS);
    },
    [applyStatusResponse, clearPollTimer, failWith],
  );

  const startLocalServerAndPoll = useCallback(
    async (token: number) => {
      setPhase("starting");
      setErrorKind(null);
      setErrorDetail("");
      try {
        const result = await startPerceptionLocalServer();
        if (runTokenRef.current !== token) return;
        const srv = result.localServer;
        setLocalServer(srv);
        if (srv.state === "running" || srv.state === "external_running") {
          setPhase("ready");
          return;
        }
        if (isServerTerminalFailure(srv)) {
          failWith("server_failed", srv.error || "");
          return;
        }
        schedulePoll(token, 0);
      } catch (error) {
        if (runTokenRef.current !== token) return;
        failWith("server_failed", errorMessage(error));
      }
    },
    [failWith, schedulePoll],
  );

  const runCheck = useCallback(
    async (allowAutoLaunch: boolean) => {
      const flags = flagsRef.current;
      if (flags.sessionClosed || flags.screenSharing || flags.screenShareStarting) return;
      if (
        allowAutoLaunch &&
        (typeof navigator === "undefined" || typeof navigator.mediaDevices?.getDisplayMedia !== "function")
      ) {
        void onStartSharingRef.current();
        return;
      }

      runTokenRef.current += 1;
      const token = runTokenRef.current;
      clearPollTimer();
      resetTransientState();
      onOpenChangeRef.current(true);
      setPhase("checking");

      const startedAt = Date.now();
      try {
        const response = await getPerceptionStatus({ probe: true });
        if (runTokenRef.current !== token) return;
        applyStatusResponse(response, true);

        const local = isLocalPerceptionBaseUrl(response.config?.baseUrl);
        if (isPerceptionServiceReady(response, local)) {
          if (allowAutoLaunch && Date.now() - startedAt < AUTO_LAUNCH_GESTURE_WINDOW_MS) {
            close();
            void onStartSharingRef.current();
            return;
          }
          setPhase("ready");
          return;
        }

        if (!local) {
          if (response.health?.ok && response.health.modelPresent === false) {
            failWith("model_mismatch");
          } else {
            failWith("unreachable", response.health?.error || "");
          }
          return;
        }

        if (response.health?.ok && response.health.modelPresent === false && !response.localServer?.managed) {
          failWith("model_mismatch");
          return;
        }

        if (
          response.localServer?.state === "starting" &&
          !response.localServer.error &&
          isSameLocalTarget(response.localServer, response.config)
        ) {
          setPhase("starting");
          schedulePoll(token, 0);
          return;
        }

        if (response.setup?.status === "missing_dependency") {
          setPhase("setup_needed");
          return;
        }
        if (response.setup?.status === "not_started") {
          if (response.setup.downloadable !== false) {
            setPhase("setup_needed");
          } else {
            failWith("missing_gguf", response.setup.message || "");
          }
          return;
        }
        if (response.setup?.status === "error") {
          failWith("setup_error", response.setup.message || "");
          return;
        }

        await startLocalServerAndPoll(token);
      } catch (error) {
        if (runTokenRef.current !== token) return;
        failWith("unknown", errorMessage(error));
      }
    },
    [applyStatusResponse, clearPollTimer, close, failWith, resetTransientState, schedulePoll, startLocalServerAndPoll],
  );

  const prepareAndStart = useCallback(async () => {
    const flags = flagsRef.current;
    if (flags.sessionClosed || flags.screenSharing || flags.screenShareStarting) return;
    runTokenRef.current += 1;
    const token = runTokenRef.current;
    clearPollTimer();
    setPhase("installing");
    setSetupTask(null);
    setInstallingPackage(undefined);
    setErrorKind(null);
    setErrorDetail("");

    try {
      let response = await getPerceptionStatus({ probe: false });
      if (runTokenRef.current !== token) return;
      applyStatusResponse(response);
      let nextSetup = response.setup ?? null;

      if (nextSetup?.status === "missing_dependency") {
        setInstallingPackage(dependencyPackageLabel(nextSetup.packageName, "torch"));
        const pythonPath = (nextSetup.pythonPath || response.localServer?.pythonPath || "").trim();
        await installMissingRuntimeDependency(
          {
            moduleName: nextSetup.moduleName?.trim() || "perception",
            ...(pythonPath ? { pythonPath } : {}),
          },
          {
            onTaskUpdate(nextTask) {
              if (runTokenRef.current === token) setSetupTask(nextTask);
            },
          },
        );
        if (runTokenRef.current !== token) return;
        setSetupTask(null);
        setInstallingPackage(undefined);
        response = await getPerceptionStatus({ probe: false });
        if (runTokenRef.current !== token) return;
        applyStatusResponse(response);
        nextSetup = response.setup ?? null;
      }

      if (nextSetup?.status === "missing_dependency" || nextSetup?.status === "error") {
        failWith("setup_error", nextSetup.message || "");
        return;
      }

      if (nextSetup && !nextSetup.modelCached) {
        if (nextSetup.downloadable === false) {
          failWith("missing_gguf", nextSetup.message || "");
          return;
        }
        const configuredModel = (response.config?.model || "").trim() || DEFAULT_PERCEPTION_MODEL;
        const assetRef: ModelAssetRef =
          configuredModel === DEFAULT_PERCEPTION_MODEL
            ? PERCEPTION_VLM_ASSET
            : { assetId: "perception.vlm", configured: true };
        const result = await downloadModelAsset(assetRef, {
          onTaskUpdate(nextTask) {
            if (runTokenRef.current === token) setSetupTask(nextTask);
          },
        });
        if (runTokenRef.current !== token) return;
        setSetupTask(null);
        response = await getPerceptionStatus({ probe: false });
        if (runTokenRef.current !== token) return;
        applyStatusResponse(response);
        const refreshedSetup: PerceptionSetupStatus = response.setup
          ? {
              ...response.setup,
              modelCached: Boolean(response.setup.modelCached || result.cached),
              status: response.setup.modelCached || result.cached ? "ready" : response.setup.status,
            }
          : {
              downloadable: true,
              modelCached: Boolean(result.cached),
              status: result.cached ? "ready" : "not_started",
            };
        setSetup(refreshedSetup);
        if (!refreshedSetup.modelCached) {
          failWith("setup_error");
          return;
        }
      }

      await startLocalServerAndPoll(token);
    } catch (error) {
      if (runTokenRef.current !== token) return;
      setSetupTask(null);
      setInstallingPackage(undefined);
      failWith("setup_error", errorMessage(error));
    }
  }, [applyStatusResponse, clearPollTimer, failWith, startLocalServerAndPoll]);

  const openAndCheck = useCallback(() => runCheck(true), [runCheck]);
  const retry = useCallback(() => runCheck(true), [runCheck]);

  const proceedToShare = useCallback(() => {
    close();
    void onStartSharingRef.current();
  }, [close]);

  useEffect(() => {
    if (!open) {
      runTokenRef.current += 1;
      clearPollTimer();
      resetTransientState();
    }
  }, [clearPollTimer, open, resetTransientState]);

  useEffect(() => {
    if (open && (screenSharing || sessionClosed)) {
      close();
    }
  }, [close, open, screenSharing, sessionClosed]);

  useEffect(
    () => () => {
      runTokenRef.current += 1;
      clearPollTimer();
    },
    [clearPollTimer],
  );

  return {
    close,
    errorDetail,
    errorKind,
    health,
    installingPackage,
    localServer,
    openAndCheck,
    phase,
    prepareAndStart,
    proceedToShare,
    retry,
    setup,
    setupTask,
    status,
  };
}
