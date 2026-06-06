import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LlmConnectionSection } from "../../../features/api-settings/LlmConnectionSection";
import type { ApiConfig } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function apiConfig(overrides: Partial<ApiConfig> = {}): ApiConfig {
  return {
    asr_extra_configs: {},
    gpt_sovits_api_path: "",
    gpt_sovits_url: "",
    is_streaming: true,
    llm_api_key: { Deepseek: "secret" },
    llm_base_url: "https://api.deepseek.com",
    llm_extra_configs: {},
    llm_model: { Deepseek: "deepseek-chat" },
    llm_provider: "Deepseek",
    t2i_extra_configs: {},
    tts_extra_configs: {},
    ...overrides,
  } as ApiConfig;
}

function renderSection(overrides: Partial<Parameters<typeof LlmConnectionSection>[0]> = {}) {
  const props: Parameters<typeof LlmConnectionSection>[0] = {
    activeApiKey: "secret",
    activeModel: "deepseek-chat",
    availableModelOptions: [
      { id: "deepseek-chat", tags: ["text"] },
      { id: "deepseek-reasoner", tags: ["text"] },
    ],
    disabled: false,
    draft: apiConfig(),
    connectionOk: false,
    connectionTestPending: false,
    fetchModelsPending: false,
    llmExtraSchema: {},
    llmProviderSelectOptions: [
      { label: "Deepseek", value: "Deepseek" },
      { label: "OpenAI", value: "OpenAI" },
    ],
    modelCandidateListId: "llm-model",
    modelUnsupportedThinking: false,
    onAdapterExtraChange: vi.fn(),
    onDraftPatch: vi.fn(),
    onFetchModels: vi.fn(),
    onTestConnection: vi.fn(),
    onProviderChange: vi.fn(),
    onProviderMapChange: vi.fn(),
    selectedOption: { id: "deepseek-chat", tags: ["text"] },
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <LlmConnectionSection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("LlmConnectionSection", () => {
  it("routes provider, connection, and model changes through public callbacks", () => {
    const { props } = renderSection();

    fireEvent.click(screen.getAllByRole("combobox")[0]);
    fireEvent.click(screen.getByRole("option", { name: "OpenAI" }));
    expect(props.onProviderChange).toHaveBeenCalledWith("OpenAI");

    fireEvent.change(screen.getByDisplayValue("https://api.deepseek.com"), {
      target: { value: "https://api.example.com/v1" },
    });
    expect(props.onDraftPatch).toHaveBeenCalledWith({ llm_base_url: "https://api.example.com/v1" });

    fireEvent.change(screen.getByDisplayValue("secret"), { target: { value: "new-secret" } });
    expect(props.onProviderMapChange).toHaveBeenCalledWith("llm_api_key", "new-secret");

    fireEvent.focus(screen.getByDisplayValue("deepseek-chat"));
    fireEvent.click(screen.getByRole("option", { name: /deepseek-reasoner/ }));
    expect(props.onProviderMapChange).toHaveBeenCalledWith("llm_model", "deepseek-reasoner");

    fireEvent.click(screen.getByRole("button", { name: "Fetch available models" }));
    expect(props.onFetchModels).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    expect(props.onTestConnection).toHaveBeenCalledTimes(1);
  });

  it("displays selected model capability badges and streams toggle changes", () => {
    const { props } = renderSection();

    expect(screen.getAllByText("Text").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("checkbox"));
    expect(props.onDraftPatch).toHaveBeenCalledWith({ is_streaming: false });
  });

  it("shows connected state after a successful connection test", () => {
    renderSection({ connectionOk: true });

    expect(screen.getByRole("button", { name: "Connected" })).toHaveClass("api-page__llm-test-button--connected");
  });
});
