import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VisionSettingsSection } from "../../../features/api-settings/VisionSettingsSection";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const modelAssetMocks = vi.hoisted(() => ({
  download: vi.fn(),
  status: vi.fn(),
}));

vi.mock("../../../entities/model-assets/repository", () => ({
  downloadModelAsset: (...args: unknown[]) => modelAssetMocks.download(...args),
  getModelAssetStatus: (...args: unknown[]) => modelAssetMocks.status(...args),
}));

describe("VisionSettingsSection", () => {
  beforeEach(() => {
    modelAssetMocks.download.mockReset();
    modelAssetMocks.status.mockReset();
  });

  it("shows remote model configuration and keeps the model editable", () => {
    const onAdapterExtraChange = vi.fn();
    const onProviderMapChange = vi.fn();
    const onSharedCredentialChange = vi.fn();
    render(
      <ToastProvider>
        <I18nProvider language="zh_CN">
          <VisionSettingsSection
            activeApiKey="sk-vision"
            activeBaseUrl="https://api.deepseek.com"
            activeModel="deepseek-flash"
            apiKeyRequired
            availableModelOptions={[
              { id: "deepseek-flash", tags: ["vision"] },
              { id: "deepseek-v4-flash-vision-exp", tags: ["vision"] },
            ]}
            disabled={false}
            draft={{ ...sampleConfig.api_config, vision_provider: "deepseek" }}
            extraSchema={{
              detail: {
                choices: ["auto", "low", "high", "original"],
                default: "auto",
                label: "图片细节级别",
                type: "str",
              },
            }}
            fetchModelsPending={false}
            onAdapterExtraChange={onAdapterExtraChange}
            onFetchModels={vi.fn()}
            onProviderChange={vi.fn()}
            onProviderMapChange={onProviderMapChange}
            onSharedCredentialChange={onSharedCredentialChange}
            providerOptions={[
              { label: "自动选择", value: "auto" },
              { label: "DeepSeek Vision", value: "deepseek" },
            ]}
            sharedLlmProvider="Deepseek"
          />
        </I18nProvider>
      </ToastProvider>,
    );

    expect(screen.getByRole("heading", { name: "视觉理解" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://api.deepseek.com")).toBeInTheDocument();
    fireEvent.focus(screen.getByDisplayValue("deepseek-flash"));
    fireEvent.click(screen.getByRole("option", { name: /deepseek-v4-flash-vision-exp/ }));
    expect(onProviderMapChange).toHaveBeenCalledWith("deepseek-v4-flash-vision-exp");
    expect(screen.getByText("图片细节级别")).toBeInTheDocument();
    expect(screen.getByText(/与 LLM 配置中的 Deepseek 共用/)).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("sk-vision"), { target: { value: "sk-shared" } });
    expect(onSharedCredentialChange).toHaveBeenCalledWith("llm_api_key", "sk-shared");
  });

  it("keeps automatic mode compact", () => {
    render(
      <ToastProvider>
        <I18nProvider language="zh_CN">
          <VisionSettingsSection
            activeApiKey=""
            activeBaseUrl=""
            activeModel=""
            apiKeyRequired={false}
            availableModelOptions={[]}
            disabled={false}
            draft={{ ...sampleConfig.api_config, vision_provider: "auto" }}
            extraSchema={{}}
            fetchModelsPending={false}
            onAdapterExtraChange={vi.fn()}
            onFetchModels={vi.fn()}
            onProviderChange={vi.fn()}
            onProviderMapChange={vi.fn()}
            onSharedCredentialChange={vi.fn()}
            providerOptions={[{ label: "自动选择", value: "auto" }]}
          />
        </I18nProvider>
      </ToastProvider>,
    );

    expect(screen.queryByText("视觉服务基础 URL")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "视觉适配器" })).toHaveTextContent("自动选择");
  });

  it("offers a Moondream model download when the cache is missing", async () => {
    const missing = {
      assetId: "vision.moondream",
      cached: false,
      downloadable: true,
      repoId: "vikhyatk/moondream2",
      source: "huggingface",
      title: "Moondream 视觉模型",
      variant: "vikhyatk/moondream2",
    };
    modelAssetMocks.status.mockResolvedValueOnce(missing).mockResolvedValueOnce({ ...missing, cached: true });
    modelAssetMocks.download.mockResolvedValue({ ...missing, cached: true, downloaded: true });

    render(
      <ToastProvider>
        <I18nProvider language="zh_CN">
          <VisionSettingsSection
            activeApiKey=""
            activeBaseUrl=""
            activeModel=""
            apiKeyRequired={false}
            availableModelOptions={[]}
            disabled={false}
            draft={{ ...sampleConfig.api_config, vision_provider: "moondream" }}
            extraSchema={{}}
            fetchModelsPending={false}
            onAdapterExtraChange={vi.fn()}
            onFetchModels={vi.fn()}
            onProviderChange={vi.fn()}
            onProviderMapChange={vi.fn()}
            onSharedCredentialChange={vi.fn()}
            providerOptions={[{ label: "Moondream（本地）", value: "moondream" }]}
          />
        </I18nProvider>
      </ToastProvider>,
    );

    expect(await screen.findByText("Moondream 模型尚未下载")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下载模型" }));
    await waitFor(() =>
      expect(modelAssetMocks.download).toHaveBeenCalledWith({ assetId: "vision.moondream" }, expect.anything()),
    );
    expect(await screen.findByText("Moondream 模型已就绪")).toBeInTheDocument();
  });
});
