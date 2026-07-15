import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatThemeManagementPage } from "../../../features/chat-stage/theme/ChatThemeManagementPage";
import { I18nProvider } from "../../../shared/i18n";
import type { ChatThemeSummary } from "../../../shared/theme/chatTheme";
import { ToastProvider } from "../../../shared/ui";

const themeContext = vi.hoisted(() => ({
  activeId: "windborne-adventure" as string | null,
  loading: false,
  refresh: vi.fn(),
  removeTheme: vi.fn(),
  switchTheme: vi.fn(),
  themes: [] as ChatThemeSummary[],
  uploadTheme: vi.fn(),
}));

vi.mock("../../../features/chat-stage/theme/ChatThemeProvider", () => ({
  useOptionalChatTheme: () => themeContext,
}));

function renderPage() {
  return render(
    <ToastProvider>
      <I18nProvider language="zh_CN">
        <MemoryRouter initialEntries={["/settings/system/chat-themes"]}>
          <Routes>
            <Route element={<ChatThemeManagementPage />} path="/settings/system/chat-themes" />
            <Route element={<h1>System settings destination</h1>} path="/settings/system" />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </ToastProvider>,
  );
}

describe("ChatThemeManagementPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    themeContext.activeId = "windborne-adventure";
    themeContext.loading = false;
    themeContext.refresh.mockResolvedValue(undefined);
    themeContext.removeTheme.mockResolvedValue(undefined);
    themeContext.switchTheme.mockResolvedValue(undefined);
    themeContext.themes = [
      {
        author: "Shinsekai",
        id: "windborne-adventure",
        name: { en: "Windborne Adventure", zh_CN: "风旅冒险" },
        source: "builtin",
        version: "1.0.0",
      },
      {
        id: "custom-theme",
        name: { zh_CN: "用户主题" },
        source: "user",
      },
    ];
    themeContext.uploadTheme.mockResolvedValue({
      id: "uploaded-theme",
      name: { zh_CN: "上传主题" },
      source: "user",
    });
  });

  it("renders theme management as a full settings page instead of the picker dialog", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "聊天主题" })).toBeInTheDocument();
    expect(screen.getByText("管理、导入并应用聊天界面主题。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回程序设置" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传 zip" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新" })).toBeInTheDocument();
    expect(screen.getByText("风旅冒险")).toBeInTheDocument();
    expect(screen.getByText("用户主题")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "聊天主题" })).not.toBeInTheDocument();
  });

  it("returns to system settings", async () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "返回程序设置" }));

    expect(await screen.findByRole("heading", { name: "System settings destination" })).toBeInTheDocument();
  });
});
