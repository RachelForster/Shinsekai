import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReminderPanel } from "../../../features/reminders/ReminderPanel";

const mocks = vi.hoisted(() => ({
  inbox: vi.fn(),
  list: vi.fn(),
  cancel: vi.fn(),
  dismiss: vi.fn(),
  window: vi.fn(),
  listen: vi.fn(),
  updates: vi.fn(),
  people: vi.fn(),
  config: vi.fn(),
}));
vi.mock("../../../entities/reminder/repository", () => ({
  getReminderInbox: mocks.inbox,
  listReminders: mocks.list,
  cancelReminder: mocks.cancel,
  dismissReminder: mocks.dismiss,
}));
vi.mock("../../../shared/desktop/remindersApi", () => ({
  reminderWindow: mocks.window,
  onRemindersChanged: mocks.listen,
  onRemindersUpdated: mocks.updates,
  onReminderWindowHidden: vi.fn().mockResolvedValue(vi.fn()),
  isReminderWindowVisible: vi.fn().mockResolvedValue(true),
}));
vi.mock("../../../entities/character/repository", () => ({ listCharacters: mocks.people }));
vi.mock("../../../entities/config/repository", () => ({ getAppConfig: mocks.config }));
vi.mock("../../../entities/files/repository", () => ({ fileUrl: (path: string) => `/files/${path}` }));

const notice = {
  id: "test-1",
  character_name: "澪",
  title: "该休息啦",
  message: "放下屏幕，休息一会儿吧。",
  due_at: "2026-09-12T23:00:00+08:00",
};
const scheduled = { ...notice, id: "scheduled-1", title: "明天喝水", recurrence: "daily", status: "active" };

describe("character reminder panel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    document.documentElement.removeAttribute("data-color-scheme");
    mocks.inbox.mockResolvedValue([]);
    mocks.list.mockResolvedValue({ reminders: [scheduled], desktop_connected: true });
    mocks.people.mockResolvedValue([{ name: "澪", sprites: [{ path: "portrait.png" }] }]);
    mocks.config.mockResolvedValue({ system_config: { theme_color: "#5599aa", ui_language: "zh_CN" } });
    mocks.listen.mockResolvedValue(vi.fn());
    mocks.updates.mockResolvedValue(vi.fn());
    mocks.window.mockResolvedValue(undefined);
    mocks.cancel.mockResolvedValue(undefined);
    mocks.dismiss.mockResolvedValue(undefined);
  });

  it("uses the app theme and remembers a top-half portrait crop", async () => {
    localStorage.setItem("shinsekai-color-scheme", "dark");
    render(<ReminderPanel />);
    expect(await screen.findByRole("img", { name: "澪" })).toHaveAttribute("src", "/files/portrait.png");
    expect(document.documentElement.style.getPropertyValue("--theme-accent")).toBe("#5599aa");
    expect(document.documentElement.dataset.colorScheme).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "管理提醒" }));
    await screen.findByRole("button", { name: "返回小卡片" });
    expect(mocks.window).toHaveBeenCalledWith("manage");
    fireEvent.click(screen.getByRole("button", { name: "头像裁切" }));
    expect(screen.getByRole("slider")).toHaveValue("0.5");
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0.35" } });
    expect(localStorage.getItem("shinsekai.reminder.portraitCrop")).toBe("0.35");
  });

  it("loads arrivals recorded before the webview subscribed and dismisses only that arrival", async () => {
    mocks.inbox.mockResolvedValue([notice]);
    render(<ReminderPanel />);
    await screen.findByText(notice.message);
    expect(screen.getByRole("heading", { name: notice.character_name })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByText(scheduled.title)).not.toBeInTheDocument();
    mocks.inbox.mockResolvedValue([]);
    fireEvent.click(screen.getByRole("button", { name: "知道啦" }));
    await waitFor(() => expect(mocks.dismiss).toHaveBeenCalledWith(notice));
    expect(mocks.cancel).not.toHaveBeenCalled();
    await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("hide"));
    expect(screen.queryByText(scheduled.title)).not.toBeInTheDocument();
  });

  it("cancels the chosen saved schedule and refreshes the pending list", async () => {
    render(<ReminderPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "管理提醒" }));
    const cancel = await screen.findByRole("button", { name: `取消日程: ${scheduled.title}` });
    mocks.list.mockResolvedValue({ reminders: [] });
    fireEvent.click(cancel);
    await waitFor(() => expect(mocks.cancel).toHaveBeenCalledWith(scheduled.id));
    await screen.findByText("暂时没有日程");
  });

  it("updates generated dialogue without leaving schedule management", async () => {
    mocks.inbox.mockResolvedValue([notice]);
    render(<ReminderPanel />);
    await screen.findByText(notice.message);
    fireEvent.click(screen.getByRole("button", { name: "管理提醒" }));
    await screen.findByRole("button", { name: "返回小卡片" });
    mocks.inbox.mockResolvedValue([{ ...notice, message: "还不去休息？" }]);
    await act(async () => mocks.updates.mock.calls[0][0]());
    expect(screen.getByRole("button", { name: "返回小卡片" })).toBeInTheDocument();
    expect(screen.getByText("还不去休息？")).toBeInTheDocument();
  });

  it("keeps the native reminder readable during a backend failure and recovers", async () => {
    mocks.inbox.mockResolvedValue([notice]);
    mocks.list.mockRejectedValue(new Error("Bridge unavailable"));
    render(<ReminderPanel />);
    await screen.findByText(notice.message);
    expect(await screen.findByRole("alert")).toHaveTextContent("Bridge unavailable");
    mocks.list.mockResolvedValue({ reminders: [] });
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("preserves selection on refresh and focuses a newly arriving reminder", async () => {
    mocks.inbox.mockResolvedValue([notice, { ...notice, id: "test-2", message: "早一点睡" }]);
    render(<ReminderPanel />);
    const choose = await screen.findByRole("button", { name: "下一条提醒" });
    fireEvent.click(choose);
    await screen.findByText("早一点睡");
    expect(screen.getByText("2/2")).toBeInTheDocument();
    await act(async () => mocks.listen.mock.calls[0][0]());
    expect(screen.getByText("早一点睡")).toBeInTheDocument();
    mocks.inbox.mockResolvedValue([{ ...notice, id: "test-3", message: "新的提醒" }, notice]);
    await act(async () => mocks.listen.mock.calls[0][0]());
    await screen.findByText("新的提醒");
  });

  it("keeps upcoming messages out of the card and returns to compact mode on arrival", async () => {
    render(<ReminderPanel />);
    await screen.findByText("把要记住的事，交给我吧。");
    expect(screen.queryByText(scheduled.message)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "管理提醒" }));
    await screen.findByRole("heading", { name: scheduled.title });
    fireEvent.click(screen.getByRole("button", { name: "返回小卡片" }));
    await screen.findByRole("button", { name: "管理提醒" });
    expect(mocks.window).toHaveBeenCalledWith("compact");
    fireEvent.click(screen.getByRole("button", { name: "管理提醒" }));
    await screen.findByRole("heading", { name: scheduled.title });
    mocks.inbox.mockResolvedValue([notice]);
    await act(async () => mocks.listen.mock.calls[0][0]());
    await screen.findByText(notice.message);
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
