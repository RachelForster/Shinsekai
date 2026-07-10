import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectRootGate, ProjectRootPrompt } from "../../../shared/desktop/ProjectRootGate";
import { I18nProvider } from "../../../shared/i18n";

const desktopMocks = vi.hoisted(() => ({
  closeDesktopWindow: vi.fn(),
  desktopRestartErrorMessage: vi.fn((error: unknown) => (error instanceof Error ? error.message : String(error))),
  getDesktopProjectRootStatus: vi.fn(),
  isTauriDesktop: vi.fn(),
  restartDesktopApp: vi.fn(),
  selectDesktopProjectRoot: vi.fn(),
}));

vi.mock("../../../shared/desktop/desktopApi", () => ({
  closeDesktopWindow: desktopMocks.closeDesktopWindow,
  desktopRestartErrorMessage: desktopMocks.desktopRestartErrorMessage,
  getDesktopProjectRootStatus: desktopMocks.getDesktopProjectRootStatus,
  isTauriDesktop: desktopMocks.isTauriDesktop,
  restartDesktopApp: desktopMocks.restartDesktopApp,
  selectDesktopProjectRoot: desktopMocks.selectDesktopProjectRoot,
}));

const conflictStatus = {
  candidates: [
    {
      hasProjectData: true,
      path: "C:\\Users\\test\\AppData\\Local\\Shinsekai",
      selectable: true,
      source: "currentAppData",
    },
    {
      hasProjectData: true,
      path: "D:\\我的游戏\\Shinsekai",
      selectable: true,
      source: "restartLogProjectRoot",
    },
  ],
  conflict: true,
  currentPath: "C:\\Users\\test\\AppData\\Local\\Shinsekai",
  locatorPath: "C:\\Users\\test\\AppData\\Roaming\\studio.shinsekai\\project-root-v1.json",
  requiresSelection: true,
};

function renderPrompt(onResolved?: () => void) {
  return render(
    <I18nProvider language="en">
      <ProjectRootPrompt onResolved={onResolved} />
    </I18nProvider>,
  );
}

describe("ProjectRootPrompt", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    desktopMocks.isTauriDesktop.mockReturnValue(true);
    desktopMocks.getDesktopProjectRootStatus.mockResolvedValue(conflictStatus);
    desktopMocks.selectDesktopProjectRoot.mockResolvedValue({
      ...conflictStatus,
      conflict: false,
      requiresSelection: false,
    });
    desktopMocks.restartDesktopApp.mockResolvedValue(undefined);
  });

  it("requires an explicit choice before persisting and restarting", async () => {
    const onResolved = vi.fn();
    renderPrompt(onResolved);

    const dialog = await screen.findByRole("dialog", { name: "Choose project data location" });
    expect(within(dialog).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    expect(onResolved).not.toHaveBeenCalled();

    const applyButton = within(dialog).getByRole("button", { name: "Use this location and restart" });
    expect(applyButton).toBeDisabled();

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(dialog).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("radio", { name: /D:\\我的游戏\\Shinsekai/ }));
    expect(applyButton).toBeEnabled();
    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(desktopMocks.selectDesktopProjectRoot).toHaveBeenCalledWith("D:\\我的游戏\\Shinsekai");
      expect(desktopMocks.restartDesktopApp).toHaveBeenCalledTimes(1);
    });
  });

  it("does not mount runtime-dependent children while project-root selection is required", async () => {
    const runtimeChild = vi.fn();
    const RuntimeChild = () => {
      runtimeChild();
      return <div>Runtime-dependent content</div>;
    };

    render(
      <I18nProvider language="en">
        <ProjectRootGate>
          <RuntimeChild />
        </ProjectRootGate>
      </I18nProvider>,
    );

    await screen.findByRole("dialog", { name: "Choose project data location" });
    expect(runtimeChild).not.toHaveBeenCalled();
    expect(screen.queryByText("Runtime-dependent content")).not.toBeInTheDocument();
  });

  it("does not prompt when the resolver found a single safe location", async () => {
    const onResolved = vi.fn();
    desktopMocks.getDesktopProjectRootStatus.mockResolvedValue({
      ...conflictStatus,
      candidates: [conflictStatus.candidates[0]],
      conflict: false,
      requiresSelection: false,
    });

    renderPrompt(onResolved);

    await waitFor(() => expect(desktopMocks.getDesktopProjectRootStatus).toHaveBeenCalledTimes(1));
    expect(onResolved).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows an offline persisted location without allowing it to be selected", async () => {
    desktopMocks.getDesktopProjectRootStatus.mockResolvedValue({
      ...conflictStatus,
      candidates: [
        conflictStatus.candidates[0],
        {
          hasProjectData: false,
          path: "D:\\detached drive\\Shinsekai",
          selectable: false,
          source: "persistedLocator",
        },
      ],
    });

    renderPrompt();

    const dialog = await screen.findByRole("dialog", { name: "Choose project data location" });
    const offline = within(dialog).getByRole("radio", { name: /D:\\detached drive\\Shinsekai/ });
    expect(offline).toBeDisabled();
    expect(within(dialog).getByText("Currently unavailable")).toBeInTheDocument();
  });

  it("fails closed and allows retrying when migration status cannot be read", async () => {
    const onResolved = vi.fn();
    desktopMocks.getDesktopProjectRootStatus
      .mockRejectedValueOnce(new Error("temporary IPC failure"))
      .mockResolvedValueOnce({
        ...conflictStatus,
        candidates: [conflictStatus.candidates[0]],
        conflict: false,
        requiresSelection: false,
      });

    renderPrompt(onResolved);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not verify the project data location: temporary IPC failure");
    expect(onResolved).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(desktopMocks.getDesktopProjectRootStatus).toHaveBeenCalledTimes(2));
    expect(onResolved).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("explains an unsupported locator without offering an overwrite", async () => {
    desktopMocks.getDesktopProjectRootStatus.mockResolvedValue({
      ...conflictStatus,
      candidates: conflictStatus.candidates.map((candidate) => ({
        ...candidate,
        selectable: false,
      })),
    });

    renderPrompt();

    const dialog = await screen.findByRole("dialog", { name: "Choose project data location" });
    expect(within(dialog).getByText(/created by an unsupported version/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Use this location and restart" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Exit application" })).toBeEnabled();
  });
});
