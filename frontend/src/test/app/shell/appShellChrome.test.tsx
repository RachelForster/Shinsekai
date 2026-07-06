import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BottomBar } from "../../../app/shell/BottomBar";
import { SidebarNav } from "../../../app/shell/SidebarNav";
import { TopBar } from "../../../app/shell/TopBar";
import { I18nProvider } from "../../../shared/i18n";

const queryMocks = vi.hoisted(() => ({
  useAppUpdateInfo: vi.fn(),
  useIsFetching: vi.fn(),
  useIsMutating: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useIsFetching: queryMocks.useIsFetching,
  useIsMutating: queryMocks.useIsMutating,
}));

vi.mock("../../../app/shell/useAppUpdateInfo", () => ({
  useAppUpdateInfo: queryMocks.useAppUpdateInfo,
}));

function renderWithI18n(children: ReactNode, initialEntries = ["/settings/api"]) {
  return render(
    <I18nProvider language="zh_CN">
      <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }} initialEntries={initialEntries}>
        {children}
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("app shell chrome", () => {
  beforeEach(() => {
    queryMocks.useAppUpdateInfo.mockReturnValue({ data: { version: "0.1.0" } });
    queryMocks.useIsFetching.mockReturnValue(0);
    queryMocks.useIsMutating.mockReturnValue(0);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: () => Promise.resolve({ stargazers_count: 12 }),
        ok: true,
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders localized primary navigation and toggles the tools button", async () => {
    const onToolsToggle = vi.fn();
    renderWithI18n(<SidebarNav onToolsToggle={onToolsToggle} toolsOpen={false} />, ["/settings/plugins"]);

    expect(screen.getByRole("navigation", { name: "设置中心导航" })).toBeInTheDocument();
    expect(screen.getByText("基础设置")).toBeInTheDocument();
    expect(screen.getByText("扩展")).toBeInTheDocument();
    expect(screen.getByText("维护诊断")).toBeInTheDocument();
    expect(screen.getByText("工作区")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /GitHub 仓库/i })).toBeInTheDocument();
    expect(await screen.findByText("12 stars")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI 服务" })).toHaveAttribute("href", "/settings/api");
    expect(screen.getByRole("link", { name: "插件管理" })).toHaveAttribute("href", "/settings/plugins");

    const tools = screen.getByRole("button", { name: "实用工具" });
    expect(tools).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(tools);
    expect(onToolsToggle).toHaveBeenCalledTimes(1);
  });

  it("links the top bar settings action to system settings", () => {
    renderWithI18n(<TopBar />);

    expect(screen.getByText("新世界程序")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "程序设置" })).toHaveAttribute("href", "/settings/system");
  });

  it("shows app version and prioritizes saving status over syncing status", () => {
    queryMocks.useAppUpdateInfo.mockReturnValue({ data: { version: "v0.2.0" } });
    queryMocks.useIsFetching.mockReturnValue(3);
    queryMocks.useIsMutating.mockReturnValue(1);

    render(
      <I18nProvider language="zh_CN">
        <BottomBar />
      </I18nProvider>,
    );

    expect(screen.getByText("By: 不二咲爱笑")).toBeInTheDocument();
    expect(screen.getByText("正在保存")).toBeInTheDocument();
    expect(screen.queryByText("正在同步")).not.toBeInTheDocument();
    expect(screen.getByText("v0.2.0")).toBeInTheDocument();
  });

  it("prefixes bare version strings and reports sync status", () => {
    queryMocks.useAppUpdateInfo.mockReturnValue({ data: { version: "0.3.0" } });
    queryMocks.useIsFetching.mockReturnValue(1);
    queryMocks.useIsMutating.mockReturnValue(0);

    render(
      <I18nProvider language="zh_CN">
        <BottomBar />
      </I18nProvider>,
    );

    expect(screen.getByText("正在同步")).toBeInTheDocument();
    expect(screen.getByText("v0.3.0")).toBeInTheDocument();
  });
});
