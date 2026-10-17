import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeSettingsSection } from "../../../features/api-settings/KnowledgeSettingsSection";
import { normalizeApiConfigForUi } from "../../../features/api-settings/apiSettingsUtils";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({ status: vi.fn(), download: vi.fn(), install: vi.fn() }));
vi.mock("../../../entities/knowledge/repository", () => ({ getKnowledgeStatus: mocks.status }));
vi.mock("../../../entities/model-assets/repository", () => ({ downloadModelAsset: mocks.download }));
vi.mock("../../../entities/chat/repository", () => ({ installMissingRuntimeDependency: mocks.install }));
vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../shared/desktop/desktopApi")>()),
  isTauriDesktop: () => false,
}));

function setup(enabled = false) {
  const onChange = vi.fn();
  render(
    <I18nProvider language="zh_CN">
      <ToastProvider>
        <KnowledgeSettingsSection
          draft={{ ...sampleConfig.api_config, knowledge_enabled: enabled }}
          onChange={onChange}
        />
      </ToastProvider>
    </I18nProvider>,
  );
  return onChange;
}

describe("Knowledge settings", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.status.mockResolvedValue({ status: "not_started", modelCached: true });
    mocks.download.mockResolvedValue({ cached: true });
    mocks.install.mockResolvedValue({});
  });

  it("checks knowledge readiness before enabling, without extraction controls", async () => {
    const onChange = setup();
    await screen.findByText("mem0 已就绪 · 模型已就绪");
    fireEvent.click(screen.getByRole("checkbox", { name: "启用资料检索" }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ knowledge_enabled: true })));
    expect(mocks.status).toHaveBeenLastCalledWith({ startLoading: false });
    expect(screen.queryByText("每 N 轮抽取")).not.toBeInTheDocument();
    expect(screen.queryByText("抽取窗口消息数")).not.toBeInTheDocument();
  });

  it("keeps retrieval disabled when the shared model is missing", async () => {
    mocks.status.mockResolvedValue({ status: "not_started", modelCached: false });
    const onChange = setup();
    await screen.findByText("mem0 已就绪 · 模型尚未下载");
    fireEvent.click(screen.getByRole("checkbox", { name: "启用资料检索" }));
    await screen.findByText("请先使用右上角按钮安装依赖并下载模型，再启用资料检索。");
    expect(onChange).not.toHaveBeenCalled();
    expect(mocks.download).not.toHaveBeenCalled();
  });

  it("updates only knowledge settings and allows disabling without setup", async () => {
    const onChange = setup(true);
    await screen.findByText("mem0 已就绪 · 模型已就绪");
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "8" } });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        knowledge_search_limit: 8,
        memory_search_limit: sampleConfig.api_config.memory_search_limit,
      }),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "启用资料检索" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ knowledge_enabled: false }));
    expect(mocks.status).toHaveBeenCalledTimes(1);
  });

  it("installs dependencies and downloads the shared embedding asset", async () => {
    const missing = { status: "missing_dependency", moduleName: "mem0", packageName: "mem0ai" };
    mocks.status
      .mockResolvedValueOnce(missing)
      .mockResolvedValueOnce(missing)
      .mockResolvedValueOnce({ status: "not_started", modelCached: false })
      .mockResolvedValue({ status: "not_started", modelCached: true });
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "安装依赖" }));
    await waitFor(() =>
      expect(mocks.download).toHaveBeenCalledWith(
        { assetId: "memory.embedding" },
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
    expect(mocks.install).toHaveBeenCalledWith({ moduleName: "mem0" }, expect.any(Object));
    await screen.findByText("mem0 已就绪 · 模型已就绪");
  });

  it("defaults missing knowledge config to disabled and bounds Top-K", () => {
    const legacy = { ...sampleConfig.api_config };
    Reflect.deleteProperty(legacy, "knowledge_enabled");
    Reflect.deleteProperty(legacy, "knowledge_search_limit");
    expect(normalizeApiConfigForUi(legacy)).toMatchObject({ knowledge_enabled: false, knowledge_search_limit: 5 });
    expect(normalizeApiConfigForUi({ ...legacy, knowledge_enabled: false, knowledge_search_limit: 99 })).toMatchObject({
      knowledge_enabled: false,
      knowledge_search_limit: 20,
    });
  });
});
