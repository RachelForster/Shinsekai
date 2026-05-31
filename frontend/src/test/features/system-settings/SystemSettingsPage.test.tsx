import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SystemSettingsPage } from "../../../features/system-settings/SystemSettingsPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { AppStateProvider } from "../../../shared/app-state/AppState";
import { ToastProvider } from "../../../shared/ui";

const mockGetAppConfig = vi.fn();

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
  saveSystemConfig: vi.fn(),
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AppStateProvider>
          <I18nProvider language="zh_CN">
            <SystemSettingsPage />
          </I18nProvider>
        </AppStateProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function mockSystemConfig() {
  return {
    system_config: {
      asr_language: "",
      asr_provider: "vosk",
      asr_whisper_compute_type: "",
      asr_whisper_device: "auto",
      asr_whisper_model_size: "base",
      font_pixel_size: 0,
      height: 0,
      live_room_id: "",
      settings_window_height: 0,
      settings_window_width: 0,
      splash_duration: 75,
      system_name: "",
      ui_language: "zh_CN",
      voice_language: "ja",
      width: 0,
    },
  };
}

describe("SystemSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows error state", async () => {
    mockGetAppConfig.mockRejectedValue(new Error("网络错误"));
    renderPage();
    expect(await screen.findByText("操作失败")).toBeInTheDocument();
  });

  it("renders the page title", async () => {
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());
    renderPage();
    expect(await screen.findByText("系统")).toBeInTheDocument();
  });
});
