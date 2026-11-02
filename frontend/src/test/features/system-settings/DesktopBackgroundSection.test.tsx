import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopBackgroundSection } from "../../../features/system-settings/DesktopBackgroundSection";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { BackgroundPreferences } from "../../../shared/desktop/backgroundApi";
import { closePreferenceChangedEvent } from "../../../shared/desktop/windowCloseApi";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  save: vi.fn(),
  autoGet: vi.fn(),
  autoSet: vi.fn(),
  window: vi.fn(),
  desktop: vi.fn(),
}));
vi.mock("../../../shared/desktop/backgroundApi", () => ({
  getBackgroundPreferences: mocks.get,
  saveBackgroundPreferences: mocks.save,
}));
vi.mock("../../../shared/desktop/autostartApi", () => ({ getAutostart: mocks.autoGet, setAutostart: mocks.autoSet }));
vi.mock("../../../shared/desktop/remindersApi", () => ({ reminderWindow: mocks.window }));
vi.mock("../../../shared/desktop/desktopApi", () => ({ isTauriDesktop: mocks.desktop }));

const preferences: BackgroundPreferences = {
  closeToTray: false,
  rememberCloseAction: false,
  minimizeToTray: false,
  language: "zh_CN",
};

function renderSection() {
  return render(
    <I18nProvider language="zh_CN">
      <DesktopBackgroundSection />
    </I18nProvider>,
  );
}

describe("desktop background settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.desktop.mockReturnValue(true);
    mocks.get.mockResolvedValue({ preferences, trayAvailable: true });
    mocks.save.mockImplementation(async (next) => ({ preferences: next, trayAvailable: true }));
    mocks.autoGet.mockResolvedValue(false);
    mocks.autoSet.mockImplementation(async (enabled) => enabled);
    mocks.window.mockResolvedValue(undefined);
  });

  it("does not expose desktop actions in the browser", () => {
    mocks.desktop.mockReturnValue(false);
    const { container } = renderSection();
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("loads saved preferences and saves independent tray and reminder controls", async () => {
    renderSection();
    const enable = await screen.findByRole("checkbox", { name: "最小化主窗口到托盘" });
    expect(enable).not.toBeChecked();
    fireEvent.click(enable);
    fireEvent.click(screen.getByRole("combobox", { name: "关闭主窗口时" }));
    fireEvent.click(screen.getByRole("option", { name: "最小化到托盘" }));
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    await screen.findByText("托盘与提醒设置已保存。");
    expect(mocks.save).toHaveBeenCalledWith({
      ...preferences,
      minimizeToTray: true,
      closeToTray: true,
      rememberCloseAction: true,
    });
  });

  it("opens all schedules and exposes no bedtime-specific controls", async () => {
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "查看所有提醒安排" }));
    expect(mocks.window).toHaveBeenCalledWith("manage");
    expect(screen.queryByText("每天提醒我睡觉")).not.toBeInTheDocument();
  });

  it("reads OS autostart state and applies changes immediately", async () => {
    mocks.autoGet.mockResolvedValue(true);
    renderSection();
    const toggle = await screen.findByRole("checkbox", { name: "登录系统时自动启动" });
    await waitFor(() => expect(toggle).toBeChecked());
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(mocks.autoSet).toHaveBeenCalledWith(false);
    expect(mocks.save).not.toHaveBeenCalled();
  });

  it("preserves the draft after a failed save and allows retry", async () => {
    mocks.save.mockRejectedValueOnce("磁盘不可写");
    renderSection();
    fireEvent.click(await screen.findByRole("checkbox", { name: "最小化主窗口到托盘" }));
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("磁盘不可写");
    expect(screen.getByRole("checkbox", { name: "最小化主窗口到托盘" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    await screen.findByText("托盘与提醒设置已保存。");
    expect(mocks.save).toHaveBeenCalledTimes(2);
  });

  it("keeps the previous autostart state after a failed OS write", async () => {
    mocks.autoSet.mockRejectedValueOnce(new Error("Access denied"));
    renderSection();
    const toggle = await screen.findByRole("checkbox", { name: "登录系统时自动启动" });
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    expect(await screen.findByRole("alert")).toHaveTextContent("Access denied");
    expect(toggle).not.toBeChecked();
  });

  it("keeps tray controls disabled when native tray creation failed", async () => {
    mocks.get.mockResolvedValue({ preferences, trayAvailable: false });
    renderSection();
    expect(await screen.findByLabelText("关闭主窗口时")).toBeEnabled();
    expect(screen.getByRole("option", { name: "最小化到托盘", hidden: true })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "最小化主窗口到托盘" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "登录系统时自动启动" })).toBeEnabled();
  });

  it("recovers from a failed initial load", async () => {
    mocks.get.mockRejectedValueOnce(new Error("无法读取设置"));
    renderSection();
    expect(await screen.findByRole("alert")).toHaveTextContent("无法读取设置");
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    await screen.findByRole("checkbox", { name: "最小化主窗口到托盘" });
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("can reset a remembered choice to ask every time", async () => {
    mocks.get.mockResolvedValue({
      preferences: { ...preferences, rememberCloseAction: true, closeToTray: true },
      trayAvailable: true,
    });
    renderSection();
    const behavior = await screen.findByRole("combobox", { name: "关闭主窗口时" });
    expect(behavior).toHaveTextContent("最小化到托盘");
    fireEvent.click(behavior);
    fireEvent.click(screen.getByRole("option", { name: "每次询问" }));
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    await screen.findByText("托盘与提醒设置已保存。");
    expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ rememberCloseAction: false }));
  });

  it("refreshes a remembered close choice without discarding other unsaved settings", async () => {
    renderSection();
    fireEvent.click(await screen.findByRole("checkbox", { name: "最小化主窗口到托盘" }));
    mocks.get.mockResolvedValue({
      preferences: { ...preferences, rememberCloseAction: true, closeToTray: true },
      trayAvailable: true,
    });
    act(() => window.dispatchEvent(new Event(closePreferenceChangedEvent)));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "关闭主窗口时" })).toHaveTextContent("最小化到托盘"),
    );
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    await screen.findByText("托盘与提醒设置已保存。");
    expect(mocks.save).toHaveBeenCalledWith(
      expect.objectContaining({ minimizeToTray: true, rememberCloseAction: true, closeToTray: true }),
    );
  });
});
