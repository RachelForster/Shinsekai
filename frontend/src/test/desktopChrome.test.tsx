import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const desktopApi = vi.hoisted(() => ({
  closeDesktopWindow: vi.fn<() => Promise<void>>(),
  getDesktopRuntimeState: vi.fn(),
  isTauriDesktop: vi.fn(),
  minimizeDesktopWindow: vi.fn<() => Promise<void>>(),
  startDesktopWindowDrag: vi.fn<() => Promise<void>>(),
  toggleMaximizeDesktopWindow: vi.fn<() => Promise<void>>(),
  updateDesktopRuntime: vi.fn(),
}));

vi.mock("../shared/desktop/desktopApi", () => desktopApi);

import { DesktopChrome } from "../shared/desktop/DesktopChrome";

describe("DesktopChrome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    desktopApi.closeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.minimizeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.startDesktopWindowDrag.mockResolvedValue(undefined);
    desktopApi.toggleMaximizeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.updateDesktopRuntime.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787", status: "ready" });
    desktopApi.getDesktopRuntimeState.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787", status: "ready" });
    desktopApi.isTauriDesktop.mockReturnValue(false);
  });

  it("renders plain children outside the Tauri desktop shell", () => {
    render(
      <DesktopChrome>
        <main>App content</main>
      </DesktopChrome>,
    );

    expect(screen.getByText("App content")).toBeInTheDocument();
    expect(screen.queryByText("Shinsekai")).not.toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).not.toHaveBeenCalled();
  });

  it("renders the custom title bar after the desktop runtime is ready", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);

    render(
      <DesktopChrome>
        <main>App content</main>
      </DesktopChrome>,
    );

    expect(await screen.findByText("Shinsekai")).toBeInTheDocument();
    expect(screen.getByText("App content")).toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).toHaveBeenCalledTimes(1);
  });

  it("keeps runtime update as the only action when the runtime is missing", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      message: "缺少 Python 运行环境",
      status: "missing",
    });

    render(
      <DesktopChrome>
        <main>App content</main>
      </DesktopChrome>,
    );

    expect(await screen.findByText("需要更新运行环境")).toBeInTheDocument();
    expect(screen.getByText("缺少 Python 运行环境")).toBeInTheDocument();
    expect(screen.queryByText("App content")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "是，更新" }));

    await waitFor(() => {
      expect(desktopApi.updateDesktopRuntime).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("App content")).toBeInTheDocument();
  });

  it("wires title bar buttons and drag region to desktop commands", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);

    const { container } = render(
      <DesktopChrome>
        <main>App content</main>
      </DesktopChrome>,
    );

    await screen.findByText("App content");
    fireEvent.click(screen.getByRole("button", { name: "最小化" }));
    fireEvent.click(screen.getByRole("button", { name: "最大化" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    fireEvent.mouseDown(container.querySelector(".desktop-titlebar")!, { button: 0 });

    expect(desktopApi.minimizeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.toggleMaximizeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.closeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.startDesktopWindowDrag).toHaveBeenCalledTimes(1);
  });
});
