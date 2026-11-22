import type { HttpTransport } from "../httpTransport";
import type { Mem0Status } from "./characterTypes";
import type {
  ApiConfig,
  AppConfig,
  ComfyUIConnectionTestResult,
  ConfigPlatform,
  LlmConnectionTestResult,
  LlmModelOption,
  ModelAssetDownloadResult,
  ModelAssetsPlatform,
  ModelAssetStatus,
  MusicCoverPlatform,
  MusicCoverRunResult,
  MusicCoverSearchResult,
  NetworkProxyDetectionResult,
  SystemConfig,
  TtsBundleDownloadResult,
  TtsBundleRecommendation,
} from "./configTypes";
import type { RuntimeDependencyInstallResult, RuntimePlatform, TaskSnapshot } from "./taskTypes";

export function createConfigHttpPlatform(transport: HttpTransport): ConfigPlatform {
  const { encodePath, requestJson, waitForTask } = transport;

  return {
    cancelTtsBundleDownload: (taskId) =>
      requestJson<TaskSnapshot<TtsBundleDownloadResult>>(`/api/tasks/${encodePath(taskId)}/cancel`, {
        method: "POST",
      }),
    async downloadTtsBundle(input, options) {
      const task = await requestJson<TaskSnapshot<TtsBundleDownloadResult>>("/api/config/tts-bundle/download", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    fetchLlmModels: (input) =>
      requestJson<LlmModelOption[]>("/api/config/llm-models", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    testLlmConnection: (input) =>
      requestJson<LlmConnectionTestResult>("/api/config/llm-connection-test", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    testComfyuiConnection: (input) =>
      requestJson<ComfyUIConnectionTestResult>("/api/config/comfyui-connection-test", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    get: () => requestJson<AppConfig>("/api/config"),
    detectNetworkProxy: () => requestJson<NetworkProxyDetectionResult>("/api/config/network-proxy/detect"),
    getMemoryStatus: (options) =>
      requestJson<Mem0Status>("/api/memory/status", {
        body: JSON.stringify({ startLoading: options?.startLoading ?? true }),
        method: "POST",
      }),
    getTtsBundleRecommendation: () => requestJson<TtsBundleRecommendation>("/api/config/tts-bundle/recommendation"),
    saveApi: (config: ApiConfig) =>
      requestJson<ApiConfig>("/api/config/api", {
        body: JSON.stringify(config),
        method: "POST",
      }),
    saveSystem: (config: SystemConfig) =>
      requestJson<SystemConfig>("/api/config/system", {
        body: JSON.stringify(config),
        method: "POST",
      }),
  };
}

export function createModelAssetsHttpPlatform(transport: HttpTransport): ModelAssetsPlatform {
  const { requestJson, waitForTask } = transport;

  return {
    async download(input, options) {
      const task = await requestJson<TaskSnapshot<ModelAssetDownloadResult>>("/api/model-assets/download", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    status: (input) =>
      requestJson<ModelAssetStatus>("/api/model-assets/status", {
        body: JSON.stringify(input),
        method: "POST",
      }),
  };
}

export function createRuntimeHttpPlatform(transport: HttpTransport): RuntimePlatform {
  const { requestJson, waitForTask } = transport;

  return {
    async installMissingDependency(input, options) {
      const task = await requestJson<TaskSnapshot<RuntimeDependencyInstallResult>>(
        "/api/runtime/install-missing-dependency",
        {
          body: JSON.stringify(input),
          method: "POST",
        },
      );
      return waitForTask(task, options);
    },
  };
}

export function createMusicCoverHttpPlatform(transport: HttpTransport): MusicCoverPlatform {
  const { requestJson, waitForTask } = transport;

  return {
    async run(input, options) {
      const task = await requestJson<TaskSnapshot<MusicCoverRunResult>>("/api/music-cover/run", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    saveConfig: (input) =>
      requestJson("/api/music-cover/config", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    search: (input) =>
      requestJson<MusicCoverSearchResult>("/api/music-cover/search", {
        body: JSON.stringify(input),
        method: "POST",
      }),
  };
}
