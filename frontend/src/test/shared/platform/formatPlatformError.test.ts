import { afterEach, describe, expect, it } from "vitest";

import {
  getActiveFrontendLanguage,
  normalizeFrontendLanguage,
  setActiveFrontendLanguage,
  translateMessage,
  translateRuntimeMessage,
} from "../../../shared/i18n";
import { LLM_PROVIDER_SILICONFLOW } from "../../../shared/constants";
import { formatPlatformError, PlatformRequestError } from "../../../shared/platform/errors";
import { LLM_PROVIDER_PRESETS } from "../../../shared/platform/standalone/ai/adapters/llm/presets";
import { buildStandaloneAdapterCatalog } from "../../../shared/platform/standalone/ai/adapters/registry";

describe("runtimeLanguage & formatPlatformError", () => {
  afterEach(() => {
    setActiveFrontendLanguage("zh_CN");
  });

  it("normalizes frontend language codes and translates runtime messages", () => {
    expect(normalizeFrontendLanguage("en-US")).toBe("en");
    expect(normalizeFrontendLanguage("ja_JP")).toBe("ja");
    expect(normalizeFrontendLanguage("zh-CN")).toBe("zh_CN");
    expect(normalizeFrontendLanguage(undefined)).toBe("zh_CN");

    setActiveFrontendLanguage("en");
    expect(getActiveFrontendLanguage()).toBe("en");
    expect(translateRuntimeMessage("plat.http.taskFailed")).toBe("Task failed.");
    expect(translateRuntimeMessage("plat.http.taskFailed", undefined, "ja")).toBe("タスクが失敗しました。");
  });

  it("formats PlatformRequestError via error.<errorCode> when present and falls back cleanly", () => {
    const knownError = new PlatformRequestError("后端回退文案", 409, "chat_already_running");
    setActiveFrontendLanguage("en");
    expect(formatPlatformError(knownError)).toBe("Chat process is already running.");
    expect(formatPlatformError(knownError, (key, values) => translateMessage("ja", key, values))).toBe(
      "チャットプロセスは既に実行中です。",
    );

    const unknownCodeError = new PlatformRequestError("Custom server message", 400, "unknown_future_code", {
      name: "Mika",
    });
    expect(unknownCodeError.errorParams).toEqual({ name: "Mika" });
    expect(formatPlatformError(unknownCodeError)).toBe("Custom server message");
    expect(formatPlatformError(new Error("Plain failure"))).toBe("Plain failure");
    expect(formatPlatformError("String failure")).toBe("String failure");
  });

  it("updates standalone preset and TTS adapter labels reactively when active language changes", () => {
    setActiveFrontendLanguage("en");
    expect(LLM_PROVIDER_PRESETS[LLM_PROVIDER_SILICONFLOW].label).toContain("SiliconFlow");
    const enCatalog = buildStandaloneAdapterCatalog("toy");
    expect(enCatalog.tts[0]?.label).toContain("Disable voice");

    setActiveFrontendLanguage("ja");
    expect(LLM_PROVIDER_PRESETS[LLM_PROVIDER_SILICONFLOW].label).toContain("SiliconFlow");
    const jaCatalog = buildStandaloneAdapterCatalog("toy");
    expect(jaCatalog.tts[0]?.label).toContain("音声オフ");
  });
});
