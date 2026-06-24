import { describe, expect, it } from "vitest";

import {
  activeMapValue,
  applyTtsProviderDefaults,
  apiSchemaWithAdapterOptions,
  catalogOptions,
  containsPathQuotes,
  DEFAULT_TTS_SERVER_URL,
  isTaskCancelledError,
  isTaskRunning,
  llmModelFetchKey,
  mergeModelOptions,
  normalizeApiAsrForSave,
  normalizeApiConfigForUi,
  normalizeAsrProvider,
  normalizeSystemAsrForSave,
  normalizeTtsProvider,
  normalizeUiLanguage,
  requiresTtsServerConfig,
  requiresTtsWorkPath,
  resolveAsrWhisperPresetValue,
  syncCompactRatioDraft,
  thinkingUnsupported,
  updateAsrExtraConfig,
  VOSK_MODEL_PATH,
  withCurrentOption,
} from "../../../features/api-settings/apiSettingsUtils";
import { sampleConfig } from "../../../shared/platform/sampleData";

describe("API settings utilities", () => {
  it("normalizes selectable values while preserving current unknown choices", () => {
    expect(normalizeUiLanguage("en")).toBe("en");
    expect(normalizeUiLanguage("ja")).toBe("ja");
    expect(normalizeUiLanguage("fr")).toBe("zh_CN");
    expect(normalizeAsrProvider("faster-whisper")).toBe("faster_whisper");
    expect(normalizeAsrProvider("RealtimeSTT")).toBe("realtime_stt");
    expect(normalizeAsrProvider("")).toBe("vosk");
    expect(resolveAsrWhisperPresetValue("large-v3")).toBe("large-v3");
    expect(resolveAsrWhisperPresetValue("custom-model")).toBe("__custom__");

    const options = [{ label: "A", value: "a" }];
    expect(withCurrentOption(options, "a")).toBe(options);
    expect(withCurrentOption(options, " custom ")).toEqual([
      { label: "A", value: "a" },
      { label: "custom", value: "custom" },
    ]);
  });

  it("builds catalog-backed API schema and keeps selected custom providers visible", () => {
    const schema = apiSchemaWithAdapterOptions(
      {
        asr: [],
        llm: [],
        t2i: [{ label: "", value: "novelai" }],
        tts: [{ label: "VoiceX", value: "voicex" }],
      },
      {
        ...sampleConfig.api_config,
        t2i_provider: "custom-t2i",
        tts_provider: "voicex",
      },
    );

    const fields = schema.flatMap((group) => group.fields);
    expect(fields.some((field) => field.name === "is_streaming")).toBe(false);
    expect(fields.find((field) => field.name === "tts_provider")?.options).toEqual([
      { label: "VoiceX", value: "voicex" },
    ]);
    expect(fields.find((field) => field.name === "t2i_provider")?.options).toEqual([
      { label: "novelai", value: "novelai" },
      { label: "custom-t2i", value: "custom-t2i" },
    ]);
    expect(catalogOptions(undefined, [{ label: "Fallback", value: "fallback" }])).toEqual([
      { label: "Fallback", value: "fallback" },
    ]);
  });

  it("uses provider-specific TTS server field copy", () => {
    const genieFields = apiSchemaWithAdapterOptions(undefined, {
      ...sampleConfig.api_config,
      tts_provider: "genie-tts",
    }).flatMap((group) => group.fields);
    expect(genieFields.find((field) => field.name === "gpt_sovits_api_path")?.label).toBe("Genie TTS 服务启动路径");
    expect(genieFields.find((field) => field.name === "gpt_sovits_url")?.label).toBe("Genie TTS 服务 URL");

    const indexFields = apiSchemaWithAdapterOptions(undefined, {
      ...sampleConfig.api_config,
      tts_provider: "index-tts",
    }).flatMap((group) => group.fields);
    expect(indexFields.find((field) => field.name === "gpt_sovits_api_path")?.label).toBe("IndexTTS 服务启动路径");

    const kagglePathField = apiSchemaWithAdapterOptions(undefined, {
      ...sampleConfig.api_config,
      tts_provider: "kaggle-gpt-sovits",
    })
      .flatMap((group) => group.fields)
      .find((field) => field.name === "gpt_sovits_api_path");
    expect(kagglePathField?.label).toBe("Kaggle GPT-SoVITS 本地路径");
    expect(kagglePathField?.disabledWhen?.({ ...sampleConfig.api_config, tts_provider: "kaggle-gpt-sovits" })).toBe(
      true,
    );
  });

  it("normalizes ASR config for saving", () => {
    const system = normalizeSystemAsrForSave({
      ...sampleConfig.system_config,
      asr_provider: "FasterWhisper",
      asr_whisper_compute_type: " int8 ",
      asr_whisper_device: " CUDA ",
      asr_whisper_model_size: "",
    });

    expect(system).toMatchObject({
      asr_provider: "faster_whisper",
      asr_whisper_compute_type: "int8",
      asr_whisper_device: "cuda",
      asr_whisper_model_size: "small",
    });

    const apiConfig = {
      ...sampleConfig.api_config,
      asr_extra_configs: {
        vosk: { model_path: "  " },
      },
    };
    expect(
      normalizeApiAsrForSave(apiConfig, { ...sampleConfig.system_config, asr_provider: "vosk" }).asr_extra_configs,
    ).toEqual({
      vosk: { model_path: VOSK_MODEL_PATH },
    });
    expect(normalizeApiAsrForSave(apiConfig, { ...sampleConfig.system_config, asr_provider: "whisper" })).toBe(
      apiConfig,
    );
    expect(
      updateAsrExtraConfig(sampleConfig.api_config, "realtimestt", "language", "en").asr_extra_configs,
    ).toMatchObject({
      realtime_stt: { language: "en" },
    });
  });

  it("normalizes API config for UI defaults and compact ratio bounds", () => {
    const normalized = normalizeApiConfigForUi({
      ...sampleConfig.api_config,
      compact_target_ratio: 0.6,
      compact_threshold: "0.4" as unknown as number,
      history_recent_messages: "bad" as unknown as number,
      llm_api_key: undefined as unknown as Record<string, string>,
      llm_base_url: "",
      llm_model: undefined as unknown as Record<string, string>,
      max_active_tool_groups: "bad" as unknown as number,
      max_tool_result_chars: "bad" as unknown as number,
    });

    expect(normalized.compact_threshold).toBe(0.4);
    expect(normalized.compact_target_ratio).toBeLessThan(0.4);
    expect(normalized.history_recent_messages).toBe(20);
    expect(normalized.max_active_tool_groups).toBe(3);
    expect(normalized.max_tool_result_chars).toBe(6000);
    expect(normalized.llm_api_key).toEqual({});
    expect(normalized.llm_model).toEqual({});
    expect(normalized.llm_base_url).toBeTruthy();

    expect(syncCompactRatioDraft({ ...sampleConfig.api_config, compact_target_ratio: 0.9 }).compact_target_ratio).toBe(
      0.35,
    );
  });

  it("applies TTS provider defaults for URL, local bundle path, and Kaggle path locking", () => {
    expect(
      normalizeApiConfigForUi(
        {
          ...sampleConfig.api_config,
          gpt_sovits_api_path: "",
          gpt_sovits_url: "",
          tts_provider: "genie-tts",
        },
        "/project/data/tts_bundles/installed/genie_tts_server/Genie-TTS-Server",
      ),
    ).toMatchObject({
      gpt_sovits_api_path: "/project/data/tts_bundles/installed/genie_tts_server/Genie-TTS-Server",
      gpt_sovits_url: DEFAULT_TTS_SERVER_URL,
      tts_provider: "genie-tts",
    });

    expect(
      applyTtsProviderDefaults(
        {
          ...sampleConfig.api_config,
          gpt_sovits_api_path: "/project/data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro-20250604",
          tts_provider: "kaggle-gpt-sovits",
        },
        "/project/data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro-20250604",
      ).gpt_sovits_api_path,
    ).toBe("");

    expect(
      applyTtsProviderDefaults({
        ...sampleConfig.api_config,
        gpt_sovits_url: "http://127.0.0.1:9880",
        tts_provider: "gpt-sovits",
      }).gpt_sovits_url,
    ).toBe(DEFAULT_TTS_SERVER_URL);
  });

  it("deduplicates model options and derives request keys", () => {
    expect(
      mergeModelOptions(
        [
          { id: " deepseek-chat ", tags: ["chat"] },
          { id: "", tags: ["skip"] },
        ],
        [
          { id: "deepseek-chat", tags: ["duplicate"] },
          { id: "deepseek-reasoner", tags: [] },
        ],
      ),
    ).toEqual([
      { id: "deepseek-chat", tags: ["chat"] },
      { id: "deepseek-reasoner", tags: [] },
    ]);

    expect(activeMapValue({ Deepseek: "key" }, "Deepseek")).toBe("key");
    expect(llmModelFetchKey({ ...sampleConfig.api_config, llm_api_key: { Deepseek: "secret" } })).toContain("secret");
  });

  it("classifies task and provider helper states", () => {
    const cancelled = new Error("cancelled");
    cancelled.name = "TaskCancelledError";
    const task = (status: "queued" | "succeeded", phase: string) => ({
      createdAt: 1,
      id: "1",
      kind: "demo",
      logs: [],
      message: "",
      phase,
      status,
      title: "Demo",
      updatedAt: 1,
    });

    expect(thinkingUnsupported(" DeepSeek-Chat ")).toBe(true);
    expect(thinkingUnsupported("deepseek-reasoner")).toBe(false);
    expect(isTaskRunning(task("queued", "queued"))).toBe(true);
    expect(isTaskRunning(task("succeeded", "done"))).toBe(false);
    expect(isTaskRunning(null)).toBe(false);
    expect(isTaskCancelledError(cancelled)).toBe(true);
    expect(isTaskCancelledError(new Error("other"))).toBe(false);
    expect(normalizeTtsProvider("Kaggle GPT SoVITS")).toBe("kaggle-gpt-sovits");
    expect(requiresTtsServerConfig("GPT-SoVITS")).toBe(true);
    expect(requiresTtsServerConfig("index-tts")).toBe(true);
    expect(requiresTtsServerConfig("cosyvoice")).toBe(false);
    expect(requiresTtsServerConfig("none")).toBe(false);
    expect(requiresTtsWorkPath("genie-tts")).toBe(true);
    expect(requiresTtsWorkPath("gpt-sovits")).toBe(true);
    expect(requiresTtsWorkPath("index-tts")).toBe(true);
    expect(requiresTtsWorkPath("kaggle-gpt-sovits")).toBe(false);
    expect(containsPathQuotes("C:\\Program Files\\App")).toBe(false);
    expect(containsPathQuotes('"C:\\Program Files\\App"')).toBe(true);
  });
});
