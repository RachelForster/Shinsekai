import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VisionSettingsSection } from "../../../features/api-settings/VisionSettingsSection";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";

describe("VisionSettingsSection", () => {
  it("shows remote model configuration and keeps the model editable", () => {
    const onProviderMapChange = vi.fn();
    render(
      <I18nProvider language="zh_CN">
        <VisionSettingsSection
          activeApiKey="sk-vision"
          activeBaseUrl="https://api.deepseek.com"
          activeModel="deepseek-flash"
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
          onAdapterExtraChange={vi.fn()}
          onFetchModels={vi.fn()}
          onProviderChange={vi.fn()}
          onProviderMapChange={onProviderMapChange}
          providerOptions={[
            { label: "自动选择", value: "auto" },
            { label: "DeepSeek Vision", value: "deepseek" },
          ]}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole("heading", { name: "视觉理解" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://api.deepseek.com")).toBeInTheDocument();
    fireEvent.focus(screen.getByDisplayValue("deepseek-flash"));
    fireEvent.click(screen.getByRole("option", { name: /deepseek-v4-flash-vision-exp/ }));
    expect(onProviderMapChange).toHaveBeenCalledWith("vision_model", "deepseek-v4-flash-vision-exp");
    expect(screen.getByText("图片细节级别")).toBeInTheDocument();
  });

  it("keeps automatic mode compact", () => {
    render(
      <I18nProvider language="zh_CN">
        <VisionSettingsSection
          activeApiKey=""
          activeBaseUrl=""
          activeModel=""
          availableModelOptions={[]}
          disabled={false}
          draft={{ ...sampleConfig.api_config, vision_provider: "auto" }}
          extraSchema={{}}
          fetchModelsPending={false}
          onAdapterExtraChange={vi.fn()}
          onFetchModels={vi.fn()}
          onProviderChange={vi.fn()}
          onProviderMapChange={vi.fn()}
          providerOptions={[{ label: "自动选择", value: "auto" }]}
        />
      </I18nProvider>,
    );

    expect(screen.queryByText("视觉服务基础 URL")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "视觉适配器" })).toHaveTextContent("自动选择");
  });
});
