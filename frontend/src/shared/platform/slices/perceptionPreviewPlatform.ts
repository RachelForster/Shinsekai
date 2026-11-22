import { effectivePerceptionModel } from "../perceptionModel";
import type { PerceptionPlatform } from "./perceptionTypes";
import { type BrowserPreviewContext, delay } from "./previewContext";

export function createPerceptionPreviewPlatform(ctx: BrowserPreviewContext): PerceptionPlatform {
  const { cachedModelAssets, config, emitChat, getChat, setChat } = ctx;

  return {
    async clear() {
      const current = getChat();
      const next = {
        ...current,
        perception: current.perception
          ? {
              ...current.perception,
              lastError: "",
              rawBuffer: { dirty: false, game: "", hasFrame: false, pendingEvents: 0, stateKeys: 0 },
              rpCache: {
                currentDigest: "",
                game: "",
                lastSalience: 0,
                playerBusy: false,
                recentDigestCount: 0,
                totalNotableEvents: 0,
                unconsumedEventCount: 0,
                updatedAt: 0,
              },
            }
          : null,
      };
      setChat(next);
      emitChat();
      return delay({ accepted: true, ok: true, perception: next.perception ?? null });
    },
    async ingest(input) {
      const current = getChat();
      const nextShare =
        typeof input.screenShareActive === "boolean"
          ? input.screenShareActive
          : input.source === "screen_share" && Boolean(input.imageBase64)
            ? true
            : Boolean(current.perception?.screenShareActive);
      const next = {
        ...current,
        perception: {
          active: nextShare || Boolean(config.api_config.perception_enabled),
          baseUrl: config.api_config.perception_base_url,
          diffThreshold: config.api_config.perception_diff_threshold,
          enabled: Boolean(config.api_config.perception_enabled),
          frameMaxSide: config.api_config.perception_frame_max_side,
          intervalSec: config.api_config.perception_interval_sec,
          captureIntervalSec: config.api_config.perception_capture_interval_sec,
          ocrIntervalSec: config.api_config.perception_ocr_interval_sec,
          ocrEnabled: Boolean(config.api_config.perception_ocr_enabled),
          lastError: "",
          model: effectivePerceptionModel(config.api_config),
          proactiveEnabled: Boolean(config.api_config.perception_proactive_enabled),
          reflexEnabled: Boolean(config.api_config.perception_reflex_enabled),
          salienceThreshold: config.api_config.perception_salience_threshold,
          screenShareActive: nextShare,
        },
      };
      setChat(next);
      emitChat();
      return delay({ accepted: true, ok: true, perception: next.perception ?? null }, 20);
    },
    async status(options) {
      const current = getChat();
      return delay({
        chatSessionActive: Boolean(current.sessionId),
        config: {
          baseUrl: config.api_config.perception_base_url,
          diffThreshold: config.api_config.perception_diff_threshold,
          enabled: Boolean(config.api_config.perception_enabled),
          frameMaxSide: config.api_config.perception_frame_max_side,
          intervalSec: config.api_config.perception_interval_sec,
          captureIntervalSec: config.api_config.perception_capture_interval_sec,
          ocrIntervalSec: config.api_config.perception_ocr_interval_sec,
          model: effectivePerceptionModel(config.api_config),
          proactiveCooldownSec: config.api_config.perception_proactive_cooldown_sec,
          proactiveEnabled: Boolean(config.api_config.perception_proactive_enabled),
          reflexCooldownSec: config.api_config.perception_reflex_cooldown_sec,
          reflexEnabled: Boolean(config.api_config.perception_reflex_enabled),
          salienceThreshold: config.api_config.perception_salience_threshold,
        },
        ...(options?.probe
          ? {
              health: {
                baseUrl: config.api_config.perception_base_url,
                configuredModel: effectivePerceptionModel(config.api_config),
                modelPresent: true,
                models: [effectivePerceptionModel(config.api_config)],
                ok: true,
              },
            }
          : {}),
        ingestUrl: "http://127.0.0.1:8787/api/perception/ingest",
        localServer: {
          baseUrl: config.api_config.perception_base_url,
          detectedPythonPath: "runtime/python.exe",
          error: "",
          logs: [],
          managed: false,
          model: effectivePerceptionModel(config.api_config),
          pid: null,
          pythonPath: config.api_config.perception_python_path || "runtime/python.exe",
          running: false,
          starting: false,
          state: "stopped",
        },
        runtime: current.perception ?? null,
        setup: {
          downloadable: !config.api_config.perception_use_gguf,
          modelCached: cachedModelAssets.has(
            `perception.vlm:${config.api_config.perception_model || "Qwen/Qwen3-VL-2B-Instruct"}`,
          ),
          pythonPath: options?.pythonPath || config.api_config.perception_python_path || "runtime/python.exe",
          status: cachedModelAssets.has(
            `perception.vlm:${config.api_config.perception_model || "Qwen/Qwen3-VL-2B-Instruct"}`,
          )
            ? "ready"
            : "not_started",
        },
      });
    },
    async testImage(options) {
      const model = options.model || effectivePerceptionModel(config.api_config);
      return delay({
        baseUrl: options.baseUrl || config.api_config.perception_base_url,
        configuredModel: model,
        imageTest: { ok: true },
        modelPresent: true,
        models: [model],
        ok: true,
      });
    },
    async startServer(input) {
      return delay({
        localServer: {
          baseUrl: input?.baseUrl || config.api_config.perception_base_url,
          detectedPythonPath: "preview-python",
          error: "",
          logs: ["[preview] Local Qwen3-VL server started."],
          managed: true,
          model: input?.model || effectivePerceptionModel(config.api_config),
          pid: 4242,
          pythonPath: input?.pythonPath || config.api_config.perception_python_path || "preview-python",
          running: true,
          starting: false,
          state: "running",
        },
        ok: true,
      });
    },
    async stopServer() {
      return delay({
        localServer: {
          baseUrl: config.api_config.perception_base_url,
          detectedPythonPath: "preview-python",
          error: "",
          logs: ["[preview] Local Qwen3-VL server stopped."],
          managed: false,
          model: effectivePerceptionModel(config.api_config),
          pid: null,
          pythonPath: config.api_config.perception_python_path || "preview-python",
          running: false,
          starting: false,
          state: "stopped",
        },
        ok: true,
      });
    },
  };
}
