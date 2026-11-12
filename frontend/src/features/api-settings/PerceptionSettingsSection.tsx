import { useEffect, useRef, useState } from "react";
import { Activity, Copy, Play, SlidersHorizontal, Square } from "lucide-react";

import type { ApiConfig } from "../../entities/config/types";
import {
  getPerceptionStatus,
  startPerceptionLocalServer,
  stopPerceptionLocalServer,
  testPerceptionImage,
} from "../../entities/perception/repository";
import { useI18n } from "../../shared/i18n";
import { DEFAULT_PERCEPTION_MODEL, effectivePerceptionModel } from "../../shared/platform/perceptionModel";
import { resolvePlatformHttpUrl } from "../../shared/platform/platform";
import type { PerceptionHealthProbe, PerceptionLocalServerStatus } from "../../shared/platform/types";
import { AsyncButton, Button, NumberInput, Switch, TextInput, useToast } from "../../shared/ui";
import { clampFloat, clampInt, DEFAULT_PERCEPTION_API_KEY, DEFAULT_PERCEPTION_BASE_URL } from "./apiSettingsUtils";

interface PerceptionSettingsSectionProps {
  disabled?: boolean;
  draft: ApiConfig;
  id?: string;
  onChange: (draft: ApiConfig) => void;
  savedUseGguf?: boolean;
}

function endpointOptions(draft: ApiConfig) {
  return {
    apiKey: draft.perception_api_key || DEFAULT_PERCEPTION_API_KEY,
    baseUrl: draft.perception_base_url || DEFAULT_PERCEPTION_BASE_URL,
    model: effectivePerceptionModel(draft),
  };
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
  savedUseGguf,
}: PerceptionSettingsSectionProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [probing, setProbing] = useState(false);
  const [serverActionPending, setServerActionPending] = useState(false);
  const [probeResult, setProbeResult] = useState<PerceptionHealthProbe | null>(null);
  const [localServer, setLocalServer] = useState<PerceptionLocalServerStatus | null>(null);
  const [resolvedIngestUrl, setResolvedIngestUrl] = useState(() => resolvePlatformHttpUrl("/api/perception/ingest"));
  const draftRef = useRef(draft);
  draftRef.current = draft;

  const patch = (changes: Partial<ApiConfig>) => onChange({ ...draftRef.current, ...changes });

  useEffect(() => {
    let cancelled = false;
    void getPerceptionStatus({ probe: false })
      .then((response) => {
        if (cancelled) return;
        if (response.ingestUrl) {
          setResolvedIngestUrl(response.ingestUrl);
        }
        if (response.localServer) {
          setLocalServer(response.localServer);
        }
      })
      .catch(() => {
        // Ignore background status sync errors on mount.
      });
    return () => {
      cancelled = true;
    };
  }, [savedUseGguf]);

  useEffect(() => {
    if (localServer?.state !== "starting") {
      return;
    }
    let cancelled = false;
    let timer: number;
    const poll = async () => {
      const response = await getPerceptionStatus({ probe: false }).catch(() => null);
      if (cancelled) return;
      const nextServer = response?.localServer;
      if (nextServer?.state === "running") {
        const probed = await getPerceptionStatus({ ...endpointOptions(draftRef.current), probe: true }).catch(
          () => null,
        );
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

  const handleProbe = async (testImage = false) => {
    setProbing(true);
    try {
      const options = endpointOptions(draftRef.current);
      if (testImage) {
        setProbeResult(await testPerceptionImage(options));
        return;
      }
      const response = await getPerceptionStatus({ ...options, probe: true });
      if (response.ingestUrl) {
        setResolvedIngestUrl(response.ingestUrl);
      }
      if (response.localServer) {
        setLocalServer(response.localServer);
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
            {isManagedRunning ? (
              <AsyncButton
                disabled={disabled || probing}
                icon={<Square aria-hidden className="button__icon" />}
                loading={serverActionPending}
                onClick={() => void handleStopLocalServer()}
                variant="danger"
              >
                {t("api.perception.stopServer")}
              </AsyncButton>
            ) : (
              <AsyncButton
                disabled={disabled || isStarting || probing}
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
              disabled={disabled || isStarting || serverActionPending}
              icon={<Activity aria-hidden className="button__icon" />}
              loading={probing}
              onClick={() => void handleProbe(true)}
            >
              {t("api.perception.probeButton")}
            </AsyncButton>
          </div>
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
