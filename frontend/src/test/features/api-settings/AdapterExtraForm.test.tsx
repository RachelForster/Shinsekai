import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdapterExtraForm } from "../../../features/api-settings/AdapterExtraForm";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderForm(overrides: Partial<Parameters<typeof AdapterExtraForm>[0]> = {}) {
  const props: Parameters<typeof AdapterExtraForm>[0] = {
    onChange: vi.fn(),
    schema: {
      reasoning_effort: { choices: ["low", "medium", "high"], default: "medium", label: "Reasoning effort" },
      temperature: { default: 0.6, label: "Temperature", max: 2, min: 0, step: 0.1, type: "float" },
      thinking_enabled: { default: true, label: "Thinking", type: "bool" },
    },
    values: { reasoning_effort: "medium", temperature: 0.6, thinking_enabled: true },
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <AdapterExtraForm {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("AdapterExtraForm", () => {
  it("routes schema field changes through the changed adapter key", () => {
    const { props } = renderForm();

    fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.9" } });
    expect(props.onChange).toHaveBeenCalledWith("temperature", 0.9);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "high" }));
    expect(props.onChange).toHaveBeenCalledWith("reasoning_effort", "high");
  });

  it("disables thinking controls when the selected model cannot use them", () => {
    renderForm({ modelUnsupportedThinking: true });

    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("combobox")).toBeDisabled();
  });

  it("translates known labelKey entries across locales and falls back to label otherwise", () => {
    const schema = {
      base_url: {
        default: "https://api.fish.audio",
        label: "Fallback URL",
        labelKey: "ops.api.tts.fishAudio.extra.baseUrl",
      },
      enable_inline_tags: {
        default: true,
        label: "Fallback Inline",
        labelKey: "ops.api.tts.fishAudio.extra.enableInlineTags",
        type: "bool",
      },
      enable_voice_instruction: {
        default: false,
        label: "Fallback Instruct",
        labelKey: "ops.api.tts.qwen3Gguf.extra.enableVoiceInstruction",
        type: "bool",
      },
      custom: { default: "", label: "Plugin Custom Option", labelKey: "unknown.plugin.field" },
    };

    const { rerender } = render(
      <I18nProvider language="zh_CN">
        <AdapterExtraForm onChange={vi.fn()} schema={schema} values={{}} />
      </I18nProvider>,
    );
    expect(screen.getByLabelText("Fish Audio API / 本地服务地址")).toBeInTheDocument();
    expect(screen.getByLabelText("启用行内语音标签（如 [laugh]、[soft whisper]）")).toBeInTheDocument();
    expect(screen.getByLabelText("启用自然语言语音指导（需服务端支持）")).toBeInTheDocument();
    expect(screen.getByLabelText("Plugin Custom Option")).toBeInTheDocument();

    rerender(
      <I18nProvider language="ja">
        <AdapterExtraForm onChange={vi.fn()} schema={schema} values={{}} />
      </I18nProvider>,
    );
    expect(screen.getByLabelText("Fish Audio API / ローカルサーバー URL")).toBeInTheDocument();
    expect(screen.getByLabelText("インライン音声タグを有効化（例: [laugh]、[soft whisper]）")).toBeInTheDocument();
    expect(screen.getByLabelText("自然言語による発話指示を有効化（サーバー対応が必要）")).toBeInTheDocument();
    expect(screen.getByLabelText("Plugin Custom Option")).toBeInTheDocument();
  });
});
