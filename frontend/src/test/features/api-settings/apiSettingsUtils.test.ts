import { describe, expect, it } from "vitest";

import {
  applyT2iSetupMode,
  containsPathQuotes,
  DEFAULT_T2I_API_URL,
  DEFAULT_T2I_OUTPUT_NODE_ID,
  DEFAULT_T2I_PROMPT_NODE_ID,
  inferT2iSetupMode,
  isT2iReadyForSprites,
  isTaskRunning,
  mergeModelOptions,
  normalizeApiAsrForSave,
  normalizeAsrProvider,
  normalizeSystemAsrForSave,
  resolveAsrWhisperPresetValue,
  updateAsrExtraConfig,
  VOSK_MODEL_PATH,
  withCurrentOption,
} from "../../../features/api-settings/apiSettingsUtils";
import type { ApiConfig, SystemConfig } from "../../../entities/config/types";
import type { TaskSnapshot } from "../../../shared/platform/types";

function apiConfig(overrides: Partial<ApiConfig> = {}): ApiConfig {
  return {
    asr_extra_configs: {},
    llm_api_key: {},
    llm_base_url: "",
    llm_model: {},
    llm_provider: "Deepseek",
    ...overrides,
  } as ApiConfig;
}

function systemConfig(overrides: Partial<SystemConfig> = {}): SystemConfig {
  return {
    asr_provider: "vosk",
    asr_whisper_compute_type: "",
    asr_whisper_device: "auto",
    asr_whisper_model_size: "small",
    ...overrides,
  } as SystemConfig;
}

function task(status: TaskSnapshot["status"]): TaskSnapshot {
  return {
    createdAt: 0,
    id: status,
    kind: "test",
    logs: [],
    message: "",
    phase: "",
    status,
    title: "",
    updatedAt: 0,
  };
}

describe("API settings utilities", () => {
  it("normalizes ASR provider aliases and save payloads", () => {
    expect(normalizeAsrProvider("faster-whisper")).toBe("faster_whisper");
    expect(normalizeAsrProvider("RealtimeSTT")).toBe("realtime_stt");
    expect(normalizeAsrProvider("")).toBe("vosk");

    expect(
      normalizeSystemAsrForSave(
        systemConfig({
          asr_provider: "RealtimeSTT",
          asr_whisper_compute_type: " float16 ",
          asr_whisper_device: " CUDA ",
          asr_whisper_model_size: "",
        }),
      ),
    ).toMatchObject({
      asr_provider: "realtime_stt",
      asr_whisper_compute_type: "float16",
      asr_whisper_device: "cuda",
      asr_whisper_model_size: "small",
    });
  });

  it("preserves custom ASR and model options for existing configs", () => {
    expect(resolveAsrWhisperPresetValue("large-v3")).toBe("large-v3");
    expect(resolveAsrWhisperPresetValue("custom-model")).toBe("__custom__");

    expect(
      withCurrentOption(
        [
          { label: "Vosk", value: "vosk" },
          { label: "RealtimeSTT", value: "realtime_stt" },
        ],
        "custom_asr",
      ),
    ).toEqual([
      { label: "Vosk", value: "vosk" },
      { label: "RealtimeSTT", value: "realtime_stt" },
      { label: "custom_asr", value: "custom_asr" },
    ]);

    expect(
      mergeModelOptions(
        [
          { id: "deepseek-chat", tags: ["stable"] },
          { id: " ", tags: ["skip"] },
        ],
        [
          { id: "deepseek-chat", tags: ["duplicate"] },
          { id: "deepseek-reasoner", tags: [] },
        ],
      ),
    ).toEqual([
      { id: "deepseek-chat", tags: ["stable"] },
      { id: "deepseek-reasoner", tags: [] },
    ]);
  });

  it("adds the default Vosk model path only when saving Vosk configs", () => {
    expect(normalizeApiAsrForSave(apiConfig(), systemConfig()).asr_extra_configs?.vosk?.model_path).toBe(
      VOSK_MODEL_PATH,
    );

    expect(
      normalizeApiAsrForSave(
        apiConfig({ asr_extra_configs: { vosk: { model_path: "D:/models/vosk" } } }),
        systemConfig(),
      ).asr_extra_configs?.vosk?.model_path,
    ).toBe("D:/models/vosk");

    expect(normalizeApiAsrForSave(apiConfig(), systemConfig({ asr_provider: "faster_whisper" }))).toEqual(apiConfig());
  });

  it("updates nested ASR extras without dropping provider-specific keys", () => {
    expect(
      updateAsrExtraConfig(
        apiConfig({
          asr_extra_configs: {
            vosk: { model_path: "D:/models/vosk", sample_rate: 16000 },
          },
        }),
        "vosk",
        "model_path",
        "D:/models/new-vosk",
      ).asr_extra_configs?.vosk,
    ).toEqual({
      model_path: "D:/models/new-vosk",
      sample_rate: 16000,
    });
  });

  it("detects running tasks and quoted paths", () => {
    expect(isTaskRunning(task("queued"))).toBe(true);
    expect(isTaskRunning(task("running"))).toBe(true);
    expect(isTaskRunning(task("succeeded"))).toBe(false);
    expect(isTaskRunning(null)).toBe(false);

    expect(containsPathQuotes('D:/Models/"bad"')).toBe(true);
    expect(containsPathQuotes("D:/Models/good")).toBe(false);
  });

  it("keeps T2I setup skippable without hiding configured engines", () => {
    const emptyComfy = apiConfig({
      t2i_api_url: DEFAULT_T2I_API_URL,
      t2i_default_workflow_path: "",
      t2i_provider: "comfyui",
      t2i_work_path: "",
    });
    const stableDiffusion = apiConfig({
      t2i_api_url: "http://127.0.0.1:7860/sdapi/v1/txt2img",
      t2i_default_workflow_path: "",
      t2i_provider: "stable diffusion",
      t2i_work_path: "",
    });

    expect(inferT2iSetupMode(emptyComfy)).toBe("skip");
    expect(inferT2iSetupMode(stableDiffusion)).toBe("local");

    expect(applyT2iSetupMode(emptyComfy, "local")).toMatchObject({
      t2i_api_url: DEFAULT_T2I_API_URL,
      t2i_output_node_id: DEFAULT_T2I_OUTPUT_NODE_ID,
      t2i_prompt_node_id: DEFAULT_T2I_PROMPT_NODE_ID,
      t2i_provider: "comfyui",
    });

    expect(isT2iReadyForSprites(emptyComfy)).toBe(false);
    expect(isT2iReadyForSprites({ ...emptyComfy, t2i_default_workflow_path: "D:/workflows/sprite.json" })).toBe(true);
    expect(isT2iReadyForSprites(stableDiffusion)).toBe(true);
  });
});
