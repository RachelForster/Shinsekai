import { describe, expect, it } from "vitest";

import {
  adapterExtraSchemaToFormGroup,
  apiConfigFormSchema,
  buildPayloadFromSchema,
  defaultAdapterExtraValue,
  hasSchemaErrors,
  validatePayloadFromSchema,
} from "../entities/config/schema";
import { sampleConfig } from "../shared/platform/sampleData";

describe("schema-driven API config", () => {
  it("derives save payload keys from the schema", () => {
    const payload = buildPayloadFromSchema(apiConfigFormSchema, sampleConfig.api_config);
    expect(payload.is_streaming).toBe(sampleConfig.api_config.is_streaming);
    expect(payload.compact_threshold).toBe(sampleConfig.api_config.compact_threshold);
    expect(payload.max_active_tool_groups).toBe(sampleConfig.api_config.max_active_tool_groups);
    expect(payload.tts_provider).toBe("gpt-sovits");
    expect(payload.t2i_provider).toBe("comfyui");
  });

  it("validates required fields, URLs, and numeric ranges before save", () => {
    const errors = validatePayloadFromSchema(apiConfigFormSchema, {
      ...sampleConfig.api_config,
      compact_target_ratio: 0.4,
      compact_threshold: 0.4,
      gpt_sovits_url: "localhost:9880",
      history_recent_messages: 0,
      max_active_tool_groups: 21,
      max_context_tokens: 2000001,
      max_tool_result_chars: 99,
      temperature: 5,
    });

    expect(hasSchemaErrors(errors)).toBe(true);
    expect(errors.compact_target_ratio).toBe("不能大于 0.35。");
    expect(errors.history_recent_messages).toBe("不能小于 1。");
    expect(errors.max_active_tool_groups).toBe("不能大于 20。");
    expect(errors.gpt_sovits_url).toBe("请输入有效的 http(s) URL。");
    expect(errors.max_context_tokens).toBe("不能大于 2000000。");
    expect(errors.max_tool_result_chars).toBe("不能小于 100。");
    expect(errors.temperature).toBe("不能大于 2。");
  });

  it("skips validation for hidden conditional fields", () => {
    const disabled = validatePayloadFromSchema(apiConfigFormSchema, {
      ...sampleConfig.api_config,
      tts_max_sentence_length: 500,
      tts_split_enabled: false,
    });
    const enabled = validatePayloadFromSchema(apiConfigFormSchema, {
      ...sampleConfig.api_config,
      tts_max_sentence_length: 500,
      tts_split_enabled: true,
    });

    expect(disabled.tts_max_sentence_length).toBeUndefined();
    expect(enabled.tts_max_sentence_length).toBe("不能大于 100。");
  });

  it("normalizes adapter extra schemas into reusable form groups", () => {
    const group = adapterExtraSchemaToFormGroup({
      disabledKeys: ["thinking_enabled"],
      disabledReason: "该模型不支持思考模式。",
      id: "llm-extra",
      schema: {
        api_secret: { label: "Secret", secret: true, type: "str" },
        mode: { choices: ["fast", "safe"], default: "safe", label: "Mode", type: "str" },
        retries: { max: 5, min: 0, type: "INT" },
        temperature: { step: 0.05, type: "float" },
        thinking_enabled: { default: true, type: "bool" },
      },
      title: "LLM Extra",
    });

    expect(group.fields.map((field) => [field.name, field.type])).toEqual([
      ["api_secret", "password"],
      ["mode", "select"],
      ["retries", "integer"],
      ["temperature", "number"],
      ["thinking_enabled", "checkbox"],
    ]);
    expect(group.fields.find((field) => field.name === "mode")?.options).toEqual([
      { label: "fast", value: "fast" },
      { label: "safe", value: "safe" },
    ]);
    expect(group.fields.find((field) => field.name === "thinking_enabled")?.disabledWhen?.({})).toBe(true);
    expect(defaultAdapterExtraValue({ type: "float" })).toBe(0);
  });
});
