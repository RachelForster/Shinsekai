import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StartupUpdatePrompt } from "../app/shell/StartupUpdatePrompt";
import { I18nProvider } from "../shared/i18n";

const desktopMocks = vi.hoisted(() => ({
  checkDesktopUpdate: vi.fn(),
  desktopRestartErrorMessage: vi.fn((error: unknown) => (error instanceof Error ? error.message : String(error))),
  installDesktopUpdate: vi.fn(),
  isTauriDesktop: vi.fn(),
  onDesktopUpdateProgress: vi.fn(),
}));

vi.mock("../shared/desktop/desktopApi", () => ({
  checkDesktopUpdate: desktopMocks.checkDesktopUpdate,
  desktopRestartErrorMessage: desktopMocks.desktopRestartErrorMessage,
  installDesktopUpdate: desktopMocks.installDesktopUpdate,
  isTauriDesktop: desktopMocks.isTauriDesktop,
  onDesktopUpdateProgress: desktopMocks.onDesktopUpdateProgress,
}));

function renderPrompt() {
  return render(
    <I18nProvider language="en">
      <StartupUpdatePrompt />
    </I18nProvider>,
  );
}

describe("StartupUpdatePrompt", () => {
  it("checks for desktop updates on startup and installs the selected update", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(true);
    desktopMocks.checkDesktopUpdate.mockResolvedValue({
      body: "Small fixes",
      date: "2026-06-07",
      version: "2.0.3",
    });
    desktopMocks.installDesktopUpdate.mockResolvedValue(undefined);
    desktopMocks.onDesktopUpdateProgress.mockResolvedValue(vi.fn());

    renderPrompt();

    const dialog = await screen.findByRole("dialog", { name: "Desktop update" });
    expect(within(dialog).getByText("Version 2.0.3 is available")).toBeInTheDocument();
    expect(within(dialog).getByText("Published: 2026-06-07")).toBeInTheDocument();
    expect(within(dialog).getByText("Small fixes")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Install and restart" }));
    expect(desktopMocks.installDesktopUpdate).toHaveBeenCalledTimes(1);
    expect(
      await within(dialog).findByText("The update was installed. Restarting the application..."),
    ).toBeInTheDocument();
  });
});
