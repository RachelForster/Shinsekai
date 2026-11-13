import { useEffect, useRef, useState } from "react";
import { Activity, Copy, DownloadCloud, Play, SlidersHorizontal, Square } from "lucide-react";

import { installMissingRuntimeDependency } from "../../entities/chat/repository";
import type { ApiConfig } from "../../entities/config/types";
import { downloadModelAsset } from "../../entities/model-assets/repository";
import {
  getPerceptionStatus,
  startPerceptionLocalServer,
  stopPerceptionLocalServer,
  testPerceptionImage,
} from "../../entities/perception/repository";
import { useI18n } from "../../shared/i18n";
import { DEFAULT_PERCEPTION_MODEL, effectivePerceptionModel } from "../../shared/platform/perceptionModel";
import { resolvePlatformHttpUrl } from "../../shared/platform/platform";
import type {
  ModelAssetRef,
  PerceptionHealthProbe,
  PerceptionLocalServerStatus,
  PerceptionSetupStatus,
  TaskSnapshot,
} from "../../shared/platform/types";
import { AsyncButton, Button, NumberInput, Switch, TaskProgress, TextInput, useToast } from "../../shared/ui";
import { clampFloat, clampInt, DEFAULT_PERCEPTION_API_KEY, DEFAULT_PERCEPTION_BASE_URL } from "./apiSettingsUtils";

interface PerceptionSettingsSectionProps {
  disabled?: boolean;
  draft: ApiConfig;
  id?: string;
  onChange: (draft: ApiConfig) => void;
  savedModel?: string;
  savedUseGguf?: boolean;
}

const PERCEPTION_VLM_ASSET = { assetId: "perception.vlm" } as const;

function dependencyPackageLabel(packageName: string | undefined, fallback: string) {
  const label = String(packageName || "")
    .replace(/(?:\[|[<>=!~]).*$/, "")
    .trim();
  return label || fallback;
}

function endpointOptions(draft: ApiConfig) {
  return {
    apiKey: draft.perception_api_key || DEFAULT_PERCEPTION_API_KEY,
    baseUrl: draft.perception_base_url || DEFAULT_PERCEPTION_BASE_URL,
    model: effectivePerceptionModel(draft),
  };
}

function statusQueryOptions(draft: ApiConfig) {
  const model = effectivePerceptionModel(draft);
  const pythonPath = (draft.perception_python_path || "").trim();
  return {
    probe: false,
    ...(model !== DEFAULT_PERCEPTION_MODEL ? { model } : {}),
    ...(pythonPath ? { pythonPath } : {}),
  };
}

function perceptionSetupStatusLabel(setup: PerceptionSetupStatus | null, t: ReturnType<typeof useI18n>["t"]) {
  if (!setup) {
    return t("api.perception.setupUnknown");
  }
  if (setup.status === "missing_dependency") {
    return t("api.perception.missingDependency", { packageName: setup.packageName || "torch" });
  }
  if (setup.status === "error") {
    return setup.message || t("api.perception.setupError");
  }
  if (setup.status === "ready" || setup.modelCached) {
    return t("api.perception.setupReady");
  }
  return setup.message || t("api.perception.setupModelMissing");
}

function perceptionActionLabel(setup: PerceptionSetupStatus | null, t: ReturnType<typeof useI18n>["t"]) {
  if (!setup) {
    return t("api.perception.checkSetup");
  }
  if (setup.status === "missing_dependency") {
    return setup.modelCached || setup.downloadable === false
      ? t("api.perception.installDependency")
      : t("api.perception.installAndDownload");
  }
  if (setup.status === "error" || setup.modelCached || setup.downloadable === false) {
    return t("api.perception.recheckModel");
  }
  return t("api.perception.downloadModel");
}

function perceptionTaskLabels(task: TaskSnapshot, t: ReturnType<typeof useI18n>["t"], dependencyPackage = "torch") {
  const dependencyTask = task.kind === "runtime-dependency-install";
  const phase =
    task.phase === "pip"
      ? t("api.perception.installingDependency", { packageName: dependencyPackage })
      : task.phase === "queued"
        ? t("api.perception.taskInProgress")
        : task.phase === "download"
          ? t("api.perception.downloading")
          : task.phase === "verify"
            ? t("api.perception.taskVerifying")
            : task.phase === "completed"
              ? t(dependencyTask ? "api.perception.dependencyInstalled" : "api.perception.modelCached")
              : task.phase === "failed"
                ? t(dependencyTask ? "api.perception.dependencyInstallFailed" : "api.perception.modelDownloadFailed")
                : undefined;
  const status =
    task.status === "running"
      ? t("api.perception.taskInProgress")
      : task.status === "succeeded"
        ? t(dependencyTask ? "api.perception.dependencyInstalled" : "api.perception.modelCached")
        : task.status === "failed"
          ? t(dependencyTask ? "api.perception.dependencyInstallFailed" : "api.perception.modelDownloadFailed")
          : undefined;
  return { phase, status };
}

function perceptionBusyLabel(
  task: TaskSnapshot | null,
  t: ReturnType<typeof useI18n>["t"],
  dependencyPackage?: string,
) {
  if (!task) {
    return dependencyPackage
      ? t("api.perception.installingDependency", { packageName: dependencyPackage })
      : t("api.perception.checking");
  }
  return perceptionTaskLabels(task, t, dependencyPackage).phase || t("api.perception.checking");
}

function formatProbeStatus(probe: PerceptionHealthProbe, t: ReturnType<typeof useI18n>["t"]) {
  if (!probe.ok) {
    return t("api.perception.statusUnreachable", { error: probe.error || "—" });
  }
  if (probe.modelPresent === false) {
    return t("api.perception.statusModelMismatch", {
      models: probe.models.length ? probe.models.join(", ") : "—",
    });
  }
  if (probe.imageTest) {
    return probe.imageTest.ok
      ? t("api.perception.imageTestPassed")
      : t("api.perception.imageTestFailed", { error: probe.imageTest.error || "—" });
  }
  return t("api.perception.statusReady");
}

function formatLocalServerStatus(server: PerceptionLocalServerStatus | null, t: ReturnType<typeof useI18n>["t"]) {
  if (!server) {
    return t("api.perception.statusUnknown");
  }
  if (server.state === "stopped") {
    return t("api.perception.serverStopped");
  }
  if (server.state === "starting") {
    return t("api.perception.serverStarting");
  }
  if (server.state === "running") {
    return t("api.perception.serverRunning");
  }
  if (server.state === "external_running") {
    return t("api.perception.serverExternalRunning");
  }
  return t("api.perception.serverFailed", { error: server.error || "—" });
}

export function PerceptionSettingsSection({
  disabled = false,
  draft,
  id,
  onChange,
  savedModel,
  savedUseGguf,
}: PerceptionSettingsSectionProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [probing, setProbing] = useState(false);
  const [serverActionPending, setServerActionPending] = useState(false);
  const [probeResult, setProbeResult] = useState<PerceptionHealthProbe | null>(null);
  const [localServer, setLocalServer] = useState<PerceptionLocalServerStatus | null>(null);
  const [setupStatus, setSetupStatus] = useState<PerceptionSetupStatus | null>(null);
  const [setupTask, setSetupTask] = useState<TaskSnapshot | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [installingDependencyPackage, setInstallingDependencyPackage] = useState<string>();
  const [resolvedIngestUrl, setResolvedIngestUrl] = useState(() => resolvePlatformHttpUrl("/api/perception/ingest"));
  const setupInFlightRef = useRef(false);
  const setupTokenRef = useRef(0);
  const draftRef = useRef(draft);
  draftRef.current = draft;

  const patch = (changes: Partial<ApiConfig>) => onChange({ ...draftRef.current, ...changes });

  useEffect(() => {
    if (setupInFlightRef.current) {
      return;
    }
    const token = setupTokenRef.current + 1;
    setupTokenRef.current = token;
    void getPerceptionStatus(statusQueryOptions(draftRef.current))
      .then((response) => {
        if (setupTokenRef.current !== token) return;
        if (response.ingestUrl) {
          setResolvedIngestUrl(response.ingestUrl);
        }
        if (response.localServer) {
          setLocalServer(response.localServer);
        }
        if (response.setup) {
          setSetupStatus(response.setup);
        }
      })
      .catch(() => {
        // Ignore background status sync errors on mount.
      });
    return () => {
      setupTokenRef.current += 1;
    };
  }, [savedUseGguf, draft.perception_use_gguf, draft.perception_model, draft.perception_python_path]);

  useEffect(() => {
    if (localServer?.state !== "starting") {
      return;
    }
    let cancelled = false;
    let timer: number;
    const poll = async () => {
      const response = await getPerceptionStatus(statusQueryOptions(draftRef.current)).catch(() => null);
      if (cancelled) return;
      const nextServer = response?.localServer;
      if (response?.setup) {
        setSetupStatus(response.setup);
      }
      if (nextServer?.state === "running") {
        const probed = await getPerceptionStatus({
          ...endpointOptions(draftRef.current),
          ...(draftRef.current.perception_python_path ? { pythonPath: draftRef.current.perception_python_path } : {}),
          probe: true,
        }).catch(() => null);
        if (cancelled) return;
        setProbeResult(probed?.health ?? null);
      }
      if (nextServer) setLocalServer(nextServer);
      if (!nextServer || nextServer.state === "starting") {
        timer = window.setTimeout(() => void poll(), 900);
      }
    };
    timer = window.setTimeout(() => void poll(), 900);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [localServer?.state]);

  const preparePerception = async () => {
    if (setupInFlightRef.current) {
      return;
    }
    setupInFlightRef.current = true;
    const token = setupTokenRef.current + 1;
    setupTokenRef.current = token;
    setPreparing(true);
    setSetupTask(null);
    try {
      let response = await getPerceptionStatus(statusQueryOptions(draftRef.current));
      if (setupTokenRef.current !== token) {
        return;
      }
      if (response.localServer) {
        setLocalServer(response.localServer);
      }
      let nextSetup = response.setup ?? null;
      setSetupStatus(nextSetup);

      if (nextSetup?.status === "missing_dependency") {
        const missing = nextSetup;
        setInstallingDependencyPackage(dependencyPackageLabel(missing.packageName, "torch"));
        const pythonPath = (draftRef.current.perception_python_path || "").trim();
        await installMissingRuntimeDependency(
          {
            moduleName: missing.moduleName?.trim() || "perception",
            ...(pythonPath ? { pythonPath } : {}),
          },
          {
            onTaskUpdate(nextTask) {
              if (setupTokenRef.current === token) {
                setSetupTask(nextTask);
              }
            },
          },
        );
        if (setupTokenRef.current !== token) {
          return;
        }
        setSetupTask(null);
        setInstallingDependencyPackage(undefined);
        response = await getPerceptionStatus(statusQueryOptions(draftRef.current));
        if (setupTokenRef.current !== token) {
          return;
        }
        if (response.localServer) {
          setLocalServer(response.localServer);
        }
        nextSetup = response.setup ?? null;
        setSetupStatus(nextSetup);
      }

      if (nextSetup?.status === "missing_dependency" || nextSetup?.status === "error") {
        showToast({
          kind: "error",
          message:
            nextSetup.status === "missing_dependency"
              ? t("api.perception.missingDependency", { packageName: nextSetup.packageName || "torch" })
              : nextSetup.message || t("api.perception.setupError"),
          title: t("api.perception.title"),
        });
        return;
      }

      if (
        !nextSetup ||
        nextSetup.modelCached ||
        nextSetup.downloadable === false ||
        draftRef.current.perception_use_gguf
      ) {
        return;
      }

      const rawModel = (draftRef.current.perception_model || "").trim() || DEFAULT_PERCEPTION_MODEL;
      const persistedModel = (savedModel || "").trim() || DEFAULT_PERCEPTION_MODEL;
      let assetRef: ModelAssetRef;
      if (rawModel === DEFAULT_PERCEPTION_MODEL) {
        assetRef = PERCEPTION_VLM_ASSET;
      } else if (savedModel !== undefined && rawModel === persistedModel) {
        assetRef = { assetId: "perception.vlm", configured: true };
      } else {
        showToast({
          kind: "info",
          message: t("api.perception.saveCustomModelFirst"),
          title: t("api.perception.title"),
        });
        return;
      }

      const result = await downloadModelAsset(assetRef, {
        onTaskUpdate(nextTask) {
          if (setupTokenRef.current === token) {
            setSetupTask(nextTask);
          }
        },
      });
      if (setupTokenRef.current !== token) {
        return;
      }
      setSetupTask(null);
      response = await getPerceptionStatus(statusQueryOptions(draftRef.current));
      if (setupTokenRef.current !== token) {
        return;
      }
      if (response.localServer) {
        setLocalServer(response.localServer);
      }
      const refreshed: PerceptionSetupStatus = response.setup
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
      setSetupStatus(refreshed);
      if (!refreshed.modelCached) {
        throw new Error(t("api.perception.modelDownloadFailed"));
      }
    } catch (error) {
      if (setupTokenRef.current === token) {
        setSetupTask(null);
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("api.perception.modelDownloadFailed"),
          title: t("api.perception.title"),
        });
      }
    } finally {
      setupInFlightRef.current = false;
      if (setupTokenRef.current === token) {
        setInstallingDependencyPackage(undefined);
        setPreparing(false);
      }
    }
  };

  const handleProbe = async (testImage = false) => {
    setProbing(true);
    try {
      const options = endpointOptions(draftRef.current);
      if (testImage) {
        setProbeResult(await testPerceptionImage(options));
        return;
      }
      const response = await getPerceptionStatus({
        ...options,
        ...(draftRef.current.perception_python_path ? { pythonPath: draftRef.current.perception_python_path } : {}),
        probe: true,
      });
      if (response.ingestUrl) {
        setResolvedIngestUrl(response.ingestUrl);
      }
      if (response.localServer) {
        setLocalServer(response.localServer);
      }
      if (response.setup) {
        setSetupStatus(response.setup);
      }
      setProbeResult(response.health ?? null);
    } catch (error) {
      const fallback: PerceptionHealthProbe = {
        baseUrl: draftRef.current.perception_base_url || DEFAULT_PERCEPTION_BASE_URL,
        configuredModel: effectivePerceptionModel(draftRef.current),
        error: error instanceof Error ? error.message : String(error),
        models: [],
        ok: false,
      };
      setProbeResult(fallback);
    } finally {
      setProbing(false);
    }
  };

  const handleStartLocalServer = async () => {
    setServerActionPending(true);
    setProbeResult(null);
    try {
      const result = await startPerceptionLocalServer({
        baseUrl: draftRef.current.perception_base_url || DEFAULT_PERCEPTION_BASE_URL,
        model: effectivePerceptionModel(draftRef.current),
        pythonPath: draftRef.current.perception_python_path || "",
      });
      const srv = result.localServer;
      setLocalServer(srv);
      if (srv.state === "running" || srv.state === "external_running") {
        await handleProbe();
      }
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
        title: t("api.perception.title"),
      });
    } finally {
      setServerActionPending(false);
    }
  };

  const handleStopLocalServer = async () => {
    setServerActionPending(true);
    try {
      const result = await stopPerceptionLocalServer();
      setLocalServer(result.localServer);
      setProbeResult(null);
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
        title: t("api.perception.title"),
      });
    } finally {
      setServerActionPending(false);
    }
  };

  const handleCopyIngestUrl = async () => {
    try {
      await navigator.clipboard?.writeText(resolvedIngestUrl);
      showToast({ kind: "success", title: t("api.perception.endpointCopied") });
    } catch {
      // Clipboard may be unavailable in non-secure browser contexts.
    }
  };

  const isManagedRunning = Boolean(localServer?.managed && localServer.running);
  const isStarting = Boolean(localServer?.state === "starting");
  const probe = isStarting ? null : probeResult;
  const status = probe ? formatProbeStatus(probe, t) : formatLocalServerStatus(localServer, t);
  const probePassed = probe?.ok && probe.modelPresent !== false && probe.imageTest?.ok !== false;
  const statusTone = probe ? (probePassed ? "running" : "failed") : localServer?.state;
  const recentServerLog = localServer?.logs.at(-1);

  return (
    <details className="section schema-section perception-settings page-section-anchor" id={id}>
      <summary className="schema-section__summary">{t("api.perception.title")}</summary>

      <div className="perception-settings__body">
        <div className="perception-settings__service">
          <span className="perception-settings__status" data-tone={statusTone} role="status">
            {status}
          </span>
          <div className="inline-actions">
            <AsyncButton
              disabled={disabled || isStarting || serverActionPending}
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              loading={preparing}
              onClick={() => void preparePerception()}
            >
              {preparing
                ? perceptionBusyLabel(setupTask, t, installingDependencyPackage)
                : perceptionActionLabel(setupStatus, t)}
            </AsyncButton>
            {isManagedRunning ? (
              <AsyncButton
                disabled={disabled || probing || preparing}
                icon={<Square aria-hidden className="button__icon" />}
                loading={serverActionPending}
                onClick={() => void handleStopLocalServer()}
                variant="danger"
              >
                {t("api.perception.stopServer")}
              </AsyncButton>
            ) : (
              <AsyncButton
                disabled={disabled || isStarting || probing || preparing}
                icon={<Play aria-hidden className="button__icon" />}
                loading={serverActionPending || isStarting}
                onClick={() => void handleStartLocalServer()}
                variant="primary"
              >
                {t("api.perception.startServer")}
              </AsyncButton>
            )}
            <AsyncButton
              aria-busy={probing}
              disabled={disabled || isStarting || serverActionPending || preparing}
              icon={<Activity aria-hidden className="button__icon" />}
              loading={probing}
              onClick={() => void handleProbe(true)}
            >
              {t("api.perception.probeButton")}
            </AsyncButton>
          </div>
        </div>

        <div className="field-row" aria-live="polite">
          <span className="field-row__label">{t("api.perception.setupStatus")}</span>
          <span className="field-row__control">
            <span className="memory-settings__status-value">{perceptionSetupStatusLabel(setupStatus, t)}</span>
            {setupTask ? (
              <TaskProgress
                labels={perceptionTaskLabels(setupTask, t, installingDependencyPackage)}
                logLimit={0}
                task={setupTask}
              />
            ) : null}
          </span>
        </div>

        <div className="perception-settings__toggles">
          <Switch
            checked={draft.perception_enabled}
            className="perception-settings__toggle"
            disabled={disabled}
            id="perception-enabled"
            onChange={(event) => patch({ perception_enabled: event.currentTarget.checked })}
          >
            {t("api.perception.enabled")}
          </Switch>

          <Switch
            checked={draft.perception_reflex_enabled}
            className="perception-settings__toggle"
            disabled={disabled}
            id="perception-reflex-enabled"
            onChange={(event) => patch({ perception_reflex_enabled: event.currentTarget.checked })}
          >
            {t("api.perception.reflexEnabled")}
          </Switch>

          <Switch
            checked={draft.perception_proactive_enabled}
            className="perception-settings__toggle"
            disabled={disabled}
            id="perception-proactive-enabled"
            onChange={(event) => patch({ perception_proactive_enabled: event.currentTarget.checked })}
          >
            {t("api.perception.proactiveEnabled")}
          </Switch>

          <Switch
            checked={draft.perception_use_gguf}
            className="perception-settings__toggle"
            disabled={disabled || serverActionPending}
            id="perception-use-gguf"
            onChange={(event) => {
              setProbeResult(null);
              patch({ perception_use_gguf: event.currentTarget.checked });
            }}
          >
            {t("api.perception.useGguf")}
          </Switch>
        </div>
        <p className="perception-settings__hint">{t("api.perception.shareHint")}</p>

        <details className="perception-settings__advanced">
          <summary className="perception-settings__advanced-summary">
            <SlidersHorizontal aria-hidden className="t2i-setup__advanced-icon" />
            <span>{t("api.perception.advancedTitle")}</span>
          </summary>

          <div className="perception-settings__advanced-body">
            <h3 className="perception-settings__group-title">{t("api.perception.modelConnection")}</h3>
            <div className="form-grid perception-settings__fields">
              <label className="field-row">
                <span className="field-row__label">{t("api.perception.model")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={disabled || draft.perception_use_gguf}
                    onChange={(event) => {
                      setProbeResult(null);
                      patch({ perception_model: event.currentTarget.value });
                    }}
                    placeholder={DEFAULT_PERCEPTION_MODEL}
                    value={draft.perception_use_gguf ? effectivePerceptionModel(draft) : draft.perception_model}
                  />
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.baseUrl")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={disabled}
                    onChange={(event) => {
                      setProbeResult(null);
                      patch({ perception_base_url: event.currentTarget.value });
                    }}
                    placeholder={DEFAULT_PERCEPTION_BASE_URL}
                    type="url"
                    value={draft.perception_base_url}
                  />
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.pythonPath")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={disabled}
                    onChange={(event) => patch({ perception_python_path: event.currentTarget.value })}
                    placeholder={localServer?.detectedPythonPath || t("api.perception.pythonPathPlaceholder")}
                    value={draft.perception_python_path}
                  />
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.apiKey")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={disabled}
                    onChange={(event) => {
                      setProbeResult(null);
                      patch({ perception_api_key: event.currentTarget.value });
                    }}
                    placeholder={DEFAULT_PERCEPTION_API_KEY}
                    type="password"
                    value={draft.perception_api_key}
                  />
                </span>
              </label>
            </div>

            <h3 className="perception-settings__group-title">{t("api.perception.captureAndReactions")}</h3>
            <div className="field-row">
              <Switch
                checked={draft.perception_ocr_enabled}
                disabled={disabled}
                id="perception-ocr-enabled"
                onChange={(event) => patch({ perception_ocr_enabled: event.currentTarget.checked })}
              >
                {t("api.perception.ocrEnabled")}
              </Switch>
              <span className="field-row__help">{t("api.perception.ocrEnabledHelp")}</span>
            </div>
            <div className="form-grid perception-settings__fields">
              <label className="field-row">
                <span className="field-row__label">{t("api.perception.captureIntervalSec")}</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={disabled}
                    max={5}
                    min={0.2}
                    onChange={(event) =>
                      patch({ perception_capture_interval_sec: clampFloat(event.currentTarget.value, 0.5, 0.2, 5) })
                    }
                    step="any"
                    value={draft.perception_capture_interval_sec}
                  />
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.ocrIntervalSec")}</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={disabled || !draft.perception_ocr_enabled}
                    max={10}
                    min={0.5}
                    onChange={(event) =>
                      patch({ perception_ocr_interval_sec: clampFloat(event.currentTarget.value, 1, 0.5, 10) })
                    }
                    step={0.5}
                    value={draft.perception_ocr_interval_sec}
                  />
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.intervalSec")}</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={disabled}
                    max={30}
                    min={0.5}
                    onChange={(event) =>
                      patch({ perception_interval_sec: clampFloat(event.currentTarget.value, 2, 0.5, 30) })
                    }
                    step={0.5}
                    value={draft.perception_interval_sec}
                  />
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.frameMaxSide")}</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={disabled}
                    max={1280}
                    min={256}
                    onChange={(event) =>
                      patch({ perception_frame_max_side: clampInt(event.currentTarget.value, 512, 256, 1280) })
                    }
                    step={64}
                    value={draft.perception_frame_max_side}
                  />
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.diffThreshold")}</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={disabled}
                    max={0.5}
                    min={0}
                    onChange={(event) =>
                      patch({ perception_diff_threshold: clampFloat(event.currentTarget.value, 0.035, 0, 0.5) })
                    }
                    step={0.005}
                    value={draft.perception_diff_threshold}
                  />
                  <span className="field-row__help">{t("api.perception.diffThresholdHelp")}</span>
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.reflexCooldownSec")}</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={disabled || !draft.perception_reflex_enabled}
                    max={60}
                    min={1}
                    onChange={(event) =>
                      patch({ perception_reflex_cooldown_sec: clampFloat(event.currentTarget.value, 15, 1, 60) })
                    }
                    step={0.5}
                    value={draft.perception_reflex_cooldown_sec}
                  />
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.salienceThreshold")}</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={disabled || !draft.perception_proactive_enabled}
                    max={1}
                    min={0}
                    onChange={(event) =>
                      patch({ perception_salience_threshold: clampFloat(event.currentTarget.value, 0.78, 0, 1) })
                    }
                    step={0.02}
                    value={draft.perception_salience_threshold}
                  />
                  <span className="field-row__help">{t("api.perception.salienceThresholdHelp")}</span>
                </span>
              </label>

              <label className="field-row">
                <span className="field-row__label">{t("api.perception.proactiveCooldownSec")}</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={disabled || !draft.perception_proactive_enabled}
                    max={300}
                    min={5}
                    onChange={(event) =>
                      patch({ perception_proactive_cooldown_sec: clampFloat(event.currentTarget.value, 25, 5, 300) })
                    }
                    step={1}
                    value={draft.perception_proactive_cooldown_sec}
                  />
                  <span className="field-row__help">{t("api.perception.proactiveCooldownHelp")}</span>
                </span>
              </label>
            </div>

            <div className="field-row">
              <span className="field-row__label">{t("api.perception.ingestEndpoint")}</span>
              <span className="field-row__control">
                <span className="api-page__model-control">
                  <TextInput aria-label={t("api.perception.ingestEndpoint")} readOnly value={resolvedIngestUrl} />
                  <Button
                    disabled={disabled}
                    icon={<Copy aria-hidden className="button__icon" />}
                    onClick={() => void handleCopyIngestUrl()}
                  >
                    {t("api.perception.copyEndpoint")}
                  </Button>
                </span>
              </span>
            </div>

            {recentServerLog ? (
              <div className="field-row">
                <span className="field-row__label">{t("api.perception.serverLog")}</span>
                <p className="perception-settings__log">{recentServerLog}</p>
              </div>
            ) : null}
          </div>
        </details>
      </div>
    </details>
  );
}
