import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopBackgroundSection } from "../../../features/system-settings/DesktopBackgroundSection";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { BackgroundPreferences } from "../../../shared/desktop/backgroundApi";

const mocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), test: vi.fn(), desktop: vi.fn() }));
vi.mock("../../../shared/desktop/backgroundApi", () => ({
  getBackgroundPreferences: mocks.get,
  saveBackgroundPreferences: mocks.save,
  testBedtimeNotification: mocks.test,
}));
vi.mock("../../../shared/desktop/desktopApi", () => ({ isTauriDesktop: mocks.desktop }));

const preferences: BackgroundPreferences = {
  bedtimeEnabled: false,
  bedtimeTime: "23:00",
  closeToTray: false,
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
    mocks.test.mockResolvedValue(undefined);
  });

  it("does not expose desktop actions in the browser", () => {
    mocks.desktop.mockReturnValue(false);
    const { container } = renderSection();
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("loads saved preferences and saves independent tray and reminder controls", async () => {
    renderSection();
    const enable = await screen.findByRole("checkbox", { name: "每天提醒我睡觉" });
    expect(enable).not.toBeChecked();
    expect(screen.getByLabelText("提醒时间（本机时间）")).toBeDisabled();
    fireEvent.click(enable);
    fireEvent.click(screen.getByRole("checkbox", { name: "关闭主窗口后驻留托盘" }));
    fireEvent.change(screen.getByLabelText("提醒时间（本机时间）"), { target: { value: "22:30" } });
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    await screen.findByText("托盘与提醒设置已保存。");
    expect(mocks.save).toHaveBeenCalledWith({
      ...preferences,
      bedtimeEnabled: true,
      bedtimeTime: "22:30",
      closeToTray: true,
    });
  });

  it("tests a notification without enabling or saving the daily reminder", async () => {
    renderSection();
    await screen.findByRole("checkbox", { name: "每天提醒我睡觉" });
    fireEvent.click(screen.getByRole("button", { name: "测试通知" }));
    await screen.findByText(/已打开角色提醒面板/);
    expect(mocks.test).toHaveBeenCalledWith("zh_CN");
    expect(mocks.save).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox", { name: "每天提醒我睡觉" })).not.toBeChecked();
  });

  it("preserves the draft after a failed save and allows retry", async () => {
    mocks.save.mockRejectedValueOnce("磁盘不可写");
    renderSection();
    fireEvent.click(await screen.findByRole("checkbox", { name: "每天提醒我睡觉" }));
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("磁盘不可写");
    expect(screen.getByRole("checkbox", { name: "每天提醒我睡觉" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    await screen.findByText("托盘与提醒设置已保存。");
    expect(mocks.save).toHaveBeenCalledTimes(2);
  });

  it("rejects empty times without sending settings to the desktop", async () => {
    renderSection();
    fireEvent.click(await screen.findByRole("checkbox", { name: "每天提醒我睡觉" }));
    fireEvent.change(screen.getByLabelText("提醒时间（本机时间）"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存托盘与提醒设置" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请输入有效时间");
    expect(mocks.save).not.toHaveBeenCalled();
  });

  it("keeps tray controls disabled when native tray creation failed", async () => {
    mocks.get.mockResolvedValue({ preferences, trayAvailable: false });
    renderSection();
    expect(await screen.findByRole("checkbox", { name: "关闭主窗口后驻留托盘" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "最小化主窗口到托盘" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "每天提醒我睡觉" })).toBeEnabled();
  });

  it("recovers from a failed initial load", async () => {
    mocks.get.mockRejectedValueOnce(new Error("无法读取设置"));
    renderSection();
    expect(await screen.findByRole("alert")).toHaveTextContent("无法读取设置");
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    await screen.findByRole("checkbox", { name: "每天提醒我睡觉" });
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
