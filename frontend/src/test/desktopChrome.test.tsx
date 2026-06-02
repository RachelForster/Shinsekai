import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
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
import { I18nProvider } from "../shared/i18n/I18nProvider";

function renderChrome(children: ReactNode) {
  return render(
    <I18nProvider language="en">
      <DesktopChrome>{children}</DesktopChrome>
    </I18nProvider>,
  );
}

describe("DesktopChrome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({ ok: true }),
        ok: true,
      }),
    );
    desktopApi.closeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.minimizeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.startDesktopWindowDrag.mockResolvedValue(undefined);
    desktopApi.toggleMaximizeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.updateDesktopRuntime.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787", status: "ready" });
    desktopApi.getDesktopRuntimeState.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787", status: "ready" });
    desktopApi.isTauriDesktop.mockReturnValue(false);
  });

  it("renders plain children outside the Tauri desktop shell", () => {
    renderChrome(<main>App content</main>);

    expect(screen.getByText("App content")).toBeInTheDocument();
    expect(screen.queryByText("Shinsekai")).not.toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).not.toHaveBeenCalled();
  });

  it("renders the custom title bar after the desktop runtime is ready", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);

    renderChrome(<main>App content</main>);

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

    renderChrome(<main>App content</main>);

    expect(await screen.findByText("Runtime update required")).toBeInTheDocument();
    expect(screen.getByText("缺少 Python 运行环境")).toBeInTheDocument();
    expect(screen.queryByText("App content")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => {
      expect(desktopApi.updateDesktopRuntime).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("App content")).toBeInTheDocument();
  });

  it("wires title bar buttons and drag region to desktop commands", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);

    const { container } = renderChrome(<main>App content</main>);

    await screen.findByText("App content");
    fireEvent.click(screen.getByRole("button", { name: "Minimize" }));
    fireEvent.click(screen.getByRole("button", { name: "Maximize" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.mouseDown(container.querySelector(".desktop-titlebar")!, { button: 0 });

    expect(desktopApi.minimizeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.toggleMaximizeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.closeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.startDesktopWindowDrag).toHaveBeenCalledTimes(1);
  });
});
