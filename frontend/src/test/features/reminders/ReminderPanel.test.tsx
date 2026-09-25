import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReminderPanel } from "../../../features/reminders/ReminderPanel";

const mocks = vi.hoisted(() => ({
  inbox: vi.fn(),
  list: vi.fn(),
  cancel: vi.fn(),
  update: vi.fn(),
  view: vi.fn(),
  viewChanged: vi.fn(),
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
  deleteReminder: mocks.cancel,
  updateReminder: mocks.update,
  dismissReminder: mocks.dismiss,
}));
vi.mock("../../../shared/desktop/remindersApi", () => ({
  reminderWindow: mocks.window,
  getReminderView: mocks.view,
  onReminderViewChanged: mocks.viewChanged,
  onRemindersChanged: mocks.listen,
  onRemindersUpdated: mocks.updates,
  onReminderWindowHidden: vi.fn().mockResolvedValue(vi.fn()),
  isReminderWindowVisible: vi.fn().mockResolvedValue(true),
}));
vi.mock("../../../entities/character/repository", () => ({ listCharacters: mocks.people }));
vi.mock("../../../entities/config/repository", () => ({ getAppConfig: mocks.config }));
vi.mock("../../../entities/files/repository", () => ({ fileUrl: (path: string) => `/files/${path}` }));
vi.mock("../../../entities/chat/repository", () => ({
  getChatSnapshot: vi.fn().mockResolvedValue({ characterSpeechDisabled: false }),
  subscribeChat: vi.fn().mockReturnValue(() => {}),
}));

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
    mocks.update.mockResolvedValue(undefined);
    mocks.view.mockResolvedValue(false);
    mocks.viewChanged.mockResolvedValue(vi.fn());
    mocks.dismiss.mockResolvedValue(undefined);
  });

  it("restores a management request made before the webview subscribed", async () => {
    mocks.view.mockResolvedValue(true);
    render(<ReminderPanel />);
    await screen.findByRole("button", { name: `编辑日程: ${scheduled.title}` });
    expect(screen.getByRole("navigation")).toHaveTextContent("全部日程");
  });

  it("edits a reminder to use a random character and preserves the draft on failure", async () => {
    mocks.view.mockResolvedValue(true);
    mocks.update.mockRejectedValueOnce(new Error("Save failed"));
    render(<ReminderPanel />);
    fireEvent.click(await screen.findByRole("button", { name: `编辑日程: ${scheduled.title}` }));
    fireEvent.change(screen.getByLabelText("日程标题"), { target: { value: "新的安排" } });
    fireEvent.change(screen.getByLabelText("提醒人物"), { target: { value: "*" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
    expect(screen.getByLabelText("日程标题")).toHaveValue("新的安排");
    expect(mocks.update).toHaveBeenCalledWith(scheduled.id, {
      title: "新的安排",
      character_name: "*",
      message: scheduled.message,
      recurrence: "daily",
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(screen.queryByRole("form")).not.toBeInTheDocument());
  });

  it("shows completed schedules for deletion without allowing edits", async () => {
    mocks.view.mockResolvedValue(true);
    mocks.list.mockResolvedValue({ reminders: [{ ...scheduled, status: "completed" }] });
    render(<ReminderPanel />);
    await screen.findByRole("button", { name: `删除日程: ${scheduled.title}` });
    expect(screen.queryByRole("button", { name: `编辑日程: ${scheduled.title}` })).not.toBeInTheDocument();
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

  it("deletes the chosen saved schedule and refreshes the pending list", async () => {
    render(<ReminderPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "管理提醒" }));
    const cancel = await screen.findByRole("button", { name: `删除日程: ${scheduled.title}` });
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
