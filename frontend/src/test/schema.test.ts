import { describe, expect, it } from "vitest";

import {
  apiConfigFormSchema,
  buildPayloadFromSchema,
  hasSchemaErrors,
  validatePayloadFromSchema,
} from "../entities/config/schema";
import { sampleConfig } from "../shared/platform/sampleData";

describe("schema-driven API config", () => {
  it("derives save payload keys from the schema", () => {
    const payload = buildPayloadFromSchema(apiConfigFormSchema, sampleConfig.api_config);
    expect(payload.is_streaming).toBe(sampleConfig.api_config.is_streaming);
    expect(payload.tts_provider).toBe("gpt-sovits");
    expect(payload.t2i_provider).toBe("comfyui");
  });

  it("validates required fields, URLs, and numeric ranges before save", () => {
    const errors = validatePayloadFromSchema(apiConfigFormSchema, {
      ...sampleConfig.api_config,
      gpt_sovits_url: "localhost:9880",
      max_context_tokens: 2000001,
      temperature: 5,
    });

    expect(hasSchemaErrors(errors)).toBe(true);
    expect(errors.gpt_sovits_url).toBe("请输入有效的 http(s) URL。");
    expect(errors.max_context_tokens).toBe("不能大于 2000000。");
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
});
