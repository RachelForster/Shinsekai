import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopCloseDialog } from "../../../shared/desktop/DesktopCloseDialog";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { CloseRequestStatus } from "../../../shared/desktop/windowCloseApi";

const api = vi.hoisted(() => ({ get: vi.fn(), listen: vi.fn(), resolve: vi.fn() }));
vi.mock("../../../shared/desktop/windowCloseApi", () => ({
  getCloseRequestStatus: api.get,
  onCloseRequested: api.listen,
  resolveCloseRequest: api.resolve,
}));

let notify: (status: CloseRequestStatus) => void;
const pending = { requested: true, trayAvailable: true };
function mount() {
  return render(
    <I18nProvider language="zh_CN">
      <DesktopCloseDialog />
    </I18nProvider>,
  );
}

describe("main window close confirmation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({ ...pending, requested: false });
    api.listen.mockImplementation(async (callback) => {
      notify = callback;
      return vi.fn();
    });
    api.resolve.mockResolvedValue(undefined);
  });

  it("receives native close requests and remembers only an explicit choice", async () => {
    mount();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    act(() => notify(pending));
    expect(screen.getByRole("dialog", { name: "要关闭 Shinsekai 吗？" })).toBeVisible();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "记住我的选择" }));
    act(() => notify(pending)); // Repeated native close keeps the user's checkbox choice.
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "最小化到托盘" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.resolve).toHaveBeenCalledWith("tray", true);
    act(() => notify(pending));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("restores a request made before the frontend mounted and exits without remembering by default", async () => {
    api.get.mockResolvedValue(pending);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "退出程序" }));
    await waitFor(() => expect(api.resolve).toHaveBeenCalledWith("exit", false));
  });

  it("Escape cancels without saving the checked remember box", async () => {
    api.get.mockResolvedValue(pending);
    mount();
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(api.resolve).toHaveBeenCalledWith("cancel", false));
  });

  it("disables tray hiding when the native tray is unavailable", async () => {
    api.get.mockResolvedValue({ ...pending, trayAvailable: false });
    mount();
    expect(await screen.findByRole("button", { name: "最小化到托盘" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "退出程序" })).toBeEnabled();
  });

  it("keeps the dialog and choice on failure so the user can retry", async () => {
    api.get.mockResolvedValue(pending);
    api.resolve.mockRejectedValueOnce(new Error("磁盘不可写"));
    mount();
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "最小化到托盘" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("磁盘不可写");
    expect(screen.getByRole("checkbox")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "最小化到托盘" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.resolve).toHaveBeenCalledTimes(2);
  });

  it("ignores duplicate clicks while the native operation is pending", async () => {
    api.get.mockResolvedValue(pending);
    let finish!: () => void;
    api.resolve.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    mount();
    const exit = await screen.findByRole("button", { name: "退出程序" });
    fireEvent.click(exit);
    fireEvent.click(exit);
    expect(api.resolve).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "最小化到托盘" })).toBeDisabled();
    await act(async () => finish());
  });
});
