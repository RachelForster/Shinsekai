import { setActiveFrontendLanguage, translateRuntimeMessage } from "../../i18n/runtimeLanguage";
import type { ConfigPlatform, ModelAssetsPlatform, MusicCoverPlatform, MusicCoverRunResult } from "./configTypes";
import { type BrowserPreviewContext, clone, delay, previewTask } from "./previewContext";
import type { RuntimePlatform } from "./taskTypes";

function looksLikeLocalModelReference(value: string) {
  const normalized = value.replace(/\\/g, "/");
  const slashCount = normalized.split("/").length - 1;
  return (
    value.startsWith(".") ||
    value.startsWith("/") ||
    value.startsWith("\\") ||
    value.startsWith("~") ||
    value.endsWith("/") ||
    value.endsWith("\\") ||
    value.includes("\\") ||
    /^[A-Za-z]:[\\/]/.test(value) ||
    slashCount > 1
  );
}

export function createConfigPreviewPlatform(ctx: BrowserPreviewContext): ConfigPlatform {
  const { config } = ctx;
  const tr = (key: Parameters<typeof translateRuntimeMessage>[0], values?: Record<string, string | number>) =>
    translateRuntimeMessage(key, values, config.system_config.ui_language);

  return {
    async cancelTtsBundleDownload(taskId) {
      const now = Date.now();
      return delay({
        createdAt: now,
        error: "",
        id: taskId,
        kind: "tts-bundle",
        logs: [],
        message: tr("plat.preview.config.ttsBundleCancelled"),
        phase: "cancelled",
        progress: null,
        result: null,
        status: "cancelled",
        title: tr("plat.preview.config.ttsBundleTitle"),
        updatedAt: now,
      });
    },
    async downloadTtsBundle(input, options) {
      const taskId = `preview-tts-${Date.now()}`;
      previewTask(
        taskId,
        {
          message: tr("plat.preview.config.ttsBundleDownloading"),
          phase: "download",
          progress: 0.35,
          status: "running",
        },
        options,
      );
      await delay(null, 160);
      previewTask(
        taskId,
        { message: tr("plat.preview.config.ttsBundleExtracting"), phase: "extract", progress: 0.82, status: "running" },
        options,
      );
      await delay(null, 160);
      const bundleRoots = {
        genie: "data/tts_bundles/installed/genie_tts_server/Genie-TTS-Server",
        gptso: "data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro-20250604",
        gptso50: "data/tts_bundles/installed/gpt_sovits_nvidia50/GPT-SoVITS-v2pro-20250604-nvidia50",
      } as const;
      const result = {
        path: bundleRoots[input.kind],
        provider: input.kind === "genie" ? "genie-tts" : "gpt-sovits",
      } as const;
      previewTask(
        taskId,
        {
          message: tr("plat.preview.config.ttsBundleReady"),
          phase: "completed",
          progress: 1,
          result,
          status: "succeeded",
        },
        options,
      );
      return delay(result);
    },
    fetchLlmModels: async () => {
      throw new Error(tr("plat.preview.config.llmModelsBridgeRequired"));
    },
    testLlmConnection: async () => {
      throw new Error(tr("plat.preview.config.llmTestBridgeRequired"));
    },
    testComfyuiConnection: async () => {
      throw new Error(tr("plat.preview.config.comfyBridgeRequired"));
    },
    get: () => delay(config),
    detectNetworkProxy: () =>
      delay({
        http_proxy_url: "",
        https_proxy_url: "",
        socks5_proxy_url: "",
        source: "browser-preview",
      }),
    getMemoryStatus: () => delay({ modelCached: true, status: "ready" as const }),
    getTtsBundleRecommendation: () =>
      delay({
        gpus: [{ device: "NVIDIA GeForce RTX 4070", vendor: "NVIDIA", vram_gb: 12 }],
        kind: "gptso",
        platform: "Browser preview",
      }),
    async saveApi(apiConfig) {
      config.api_config = clone(apiConfig);
      return delay(config.api_config);
    },
    async saveSystem(systemConfig) {
      config.system_config = clone(systemConfig);
      setActiveFrontendLanguage(systemConfig.ui_language);
      return delay(config.system_config);
    },
  };
}

export function createModelAssetsPreviewPlatform(ctx: BrowserPreviewContext): ModelAssetsPlatform {
  const { cachedModelAssets, config } = ctx;
  const tr = (key: Parameters<typeof translateRuntimeMessage>[0], values?: Record<string, string | number>) =>
    translateRuntimeMessage(key, values, config.system_config.ui_language);

  return {
    async download(input, options) {
      const memoryEmbedding = input.assetId === "memory.embedding";
      const moondreamVision = input.assetId === "vision.moondream";
      const perceptionVlm = input.assetId === "perception.vlm";
      const variant = memoryEmbedding
        ? "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        : moondreamVision
          ? "vikhyatk/moondream2"
          : perceptionVlm
            ? String(
                (input.configured ? config.api_config.perception_model : input.variant) || "Qwen/Qwen3-VL-2B-Instruct",
              )
            : String((input.configured ? config.system_config.asr_whisper_model_size : input.variant) || "small");
      const local = Boolean(
        !memoryEmbedding && !moondreamVision && input.configured && looksLikeLocalModelReference(variant),
      );
      const repoId =
        memoryEmbedding || moondreamVision || perceptionVlm
          ? variant
          : variant.includes("/")
            ? variant
            : `Systran/faster-whisper-${variant}`;
      const key = `${input.assetId}:${variant}`;
      const taskId = `preview-model-${Date.now()}`;
      previewTask(
        taskId,
        {
          kind: "model-download",
          message: tr("plat.preview.config.modelDownloading", { variant }),
          phase: "download",
          progress: 0.42,
          status: "running",
          title: tr("plat.preview.config.modelDownloadTitle"),
        },
        options,
      );
      await delay(null, 180);
      const result = {
        assetId: input.assetId,
        cached: true,
        downloadable: !local,
        downloaded: !local,
        path: local ? variant : `preview-cache/${variant}`,
        ...(local ? {} : { repoId }),
        source: local ? ("local" as const) : ("huggingface" as const),
        title: memoryEmbedding
          ? "Long-term memory embedding"
          : moondreamVision
            ? "Moondream vision"
            : perceptionVlm
              ? `Perception VLM (${variant})`
              : "Whisper ASR",
        variant,
      };
      if (!local) {
        cachedModelAssets.add(key);
      }
      previewTask(
        taskId,
        {
          kind: "model-download",
          message: tr("plat.preview.config.modelCached", { variant }),
          phase: "completed",
          progress: 1,
          result,
          status: "succeeded",
          title: tr("plat.preview.config.modelDownloadTitle"),
        },
        options,
      );
      return result;
    },
    status(input) {
      const memoryEmbedding = input.assetId === "memory.embedding";
      const moondreamVision = input.assetId === "vision.moondream";
      const perceptionVlm = input.assetId === "perception.vlm";
      const variant = memoryEmbedding
        ? "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        : moondreamVision
          ? "vikhyatk/moondream2"
          : perceptionVlm
            ? String(
                (input.configured ? config.api_config.perception_model : input.variant) || "Qwen/Qwen3-VL-2B-Instruct",
              )
            : String((input.configured ? config.system_config.asr_whisper_model_size : input.variant) || "small");
      const local = Boolean(
        !memoryEmbedding && !moondreamVision && input.configured && looksLikeLocalModelReference(variant),
      );
      const repoId =
        memoryEmbedding || moondreamVision || perceptionVlm
          ? variant
          : variant.includes("/")
            ? variant
            : `Systran/faster-whisper-${variant}`;
      return delay({
        assetId: input.assetId,
        cached: local || cachedModelAssets.has(`${input.assetId}:${variant}`),
        downloadable: !local,
        ...(local ? { path: variant } : { repoId }),
        source: local ? ("local" as const) : ("huggingface" as const),
        title: memoryEmbedding
          ? "Long-term memory embedding"
          : moondreamVision
            ? "Moondream vision"
            : perceptionVlm
              ? `Perception VLM (${variant})`
              : "Whisper ASR",
        variant,
      });
    },
  };
}

export function createRuntimePreviewPlatform(): RuntimePlatform {
  return {
    installMissingDependency: (input) =>
      delay({
        message: `Preview installed ${input.moduleName}`,
        moduleName: input.moduleName,
        packageName: input.moduleName,
        pipCode: 0,
        pipOutput: "",
      }),
  };
}

export function createMusicCoverPreviewPlatform(ctx: BrowserPreviewContext): MusicCoverPlatform {
  const { config } = ctx;
  const tr = (key: Parameters<typeof translateRuntimeMessage>[0], values?: Record<string, string | number>) =>
    translateRuntimeMessage(key, values, config.system_config.ui_language);

  return {
    async run(input, options) {
      const taskId = `preview-music-cover-${Date.now()}`;
      previewTask<MusicCoverRunResult>(
        taskId,
        {
          kind: "music-cover",
          message: tr("plat.preview.config.musicCoverRunning"),
          phase: "run",
          progress: 0.45,
          status: "running",
          title: tr("plat.preview.config.musicCoverTitle"),
        },
        options,
      );
      await delay(null, 180);
      const result = {
        audioPath: `${config.system_config.music_cover_work_dir || "./data/music_cover"}/preview/final_mix.wav`,
        log: [
          `source=${input.source}`,
          `query=${input.query || "(empty)"}`,
          `pick_index=${input.pickIndex}`,
          `skip_rvc=${input.skipRvc}`,
          tr("plat.preview.config.musicCoverLogHint"),
        ].join("\n"),
      };
      previewTask<MusicCoverRunResult>(
        taskId,
        {
          kind: "music-cover",
          message: tr("plat.preview.config.musicCoverDone"),
          phase: "completed",
          progress: 1,
          result,
          status: "succeeded",
          title: tr("plat.preview.config.musicCoverTitle"),
        },
        options,
      );
      return delay(result);
    },
    async saveConfig(input) {
      config.system_config = {
        ...config.system_config,
        ...input,
        music_cover_ffmpeg_exe: input.music_cover_ffmpeg_exe || "",
        music_cover_rvc_cmd_template: input.music_cover_rvc_cmd_template || "",
        music_cover_rvc_device: input.music_cover_rvc_device || "cuda:0",
        music_cover_rvc_f0_method: input.music_cover_rvc_f0_method || "rmvpe",
        music_cover_rvc_index_path: input.music_cover_rvc_index_path || "",
        music_cover_rvc_model_path: input.music_cover_rvc_model_path || "",
        music_cover_rvc_model_version: input.music_cover_rvc_model_version || "v2",
        music_cover_uvr_cmd_template: input.music_cover_uvr_cmd_template || "",
        music_cover_work_dir: input.music_cover_work_dir || "./data/music_cover",
        music_cover_yt_dlp_exe: input.music_cover_yt_dlp_exe || "",
      };
      return delay({
        message: tr("plat.preview.config.musicCoverSaved"),
        systemConfig: config.system_config,
      });
    },
    search: (input) =>
      delay({
        log: [`source=${input.source}`, `query=${input.query || "(empty)"}`, "1. Preview result - sample song"].join(
          "\n",
        ),
      }),
  };
}
