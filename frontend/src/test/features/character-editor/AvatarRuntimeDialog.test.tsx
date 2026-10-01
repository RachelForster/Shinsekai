import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AvatarRuntimeDialog } from "../../../features/character-editor/AvatarRuntimeDialog";
import { I18nProvider } from "../../../shared/i18n";
import type { ShinsekaiPlatform } from "../../../shared/platform/types";
import type { AvatarFormat } from "../../../modules/character-visual";

const pick = vi.hoisted(() => vi.fn());
vi.mock("../../../shared/desktop/desktopApi", () => ({ isTauriDesktop: () => true, pickDesktopNativePath: pick }));
const status = vi.fn(),
  prepare = vi.fn(),
  install = vi.fn(),
  compile = vi.fn(),
  openExternal = vi.fn();
const format: AvatarFormat<unknown, unknown> = {
  id: "demo",
  label: "Test format",
  capabilities: { mouth: false, blink: false, motion: false, sampling: "none" },
  load: vi.fn(),
  runtime: {
    name: "Test SDK",
    version: "test-1",
    downloadUrl: "https://example.com/sdk",
    licenseUrls: ["https://example.com/core", "https://example.com/framework"],
    compile,
  },
};
beforeEach(() => {
  vi.clearAllMocks();
  status.mockResolvedValue({ installed: false });
  prepare.mockResolvedValue({ opaque: true });
  compile.mockResolvedValue("compiled");
  install.mockResolvedValue({ installed: true });
  pick.mockResolvedValue(["C:/Downloads/sdk.zip"]);
  window.__SHINSEKAI_IPC__ = {
    avatarRuntimes: { status, prepare, install },
    files: { openExternal },
  } as unknown as ShinsekaiPlatform;
});
afterEach(() => {
  cleanup();
  delete window.__SHINSEKAI_IPC__;
});
function view(selectedFormat = format) {
  const onInstalled = vi.fn(),
    onClose = vi.fn(),
    onReload = vi.fn();
  render(
    <I18nProvider language="en">
      <AvatarRuntimeDialog format={selectedFormat} onClose={onClose} onInstalled={onInstalled} onReload={onReload} />
    </I18nProvider>,
  );
  return { onInstalled, onClose, onReload };
}
async function selectAndAccept() {
  await screen.findByText("SDK not installed");
  fireEvent.click(screen.getByRole("button", { name: "Select SDK ZIP" }));
  await waitFor(() => expect(screen.getByTitle("C:/Downloads/sdk.zip")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("checkbox"));
}
describe("user-installed format runtime dialog", () => {
  it("opens official download and license links without installing or accepting implicitly", async () => {
    view();
    await screen.findByText("SDK not installed");
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Import and install" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Open official download page" }));
    expect(openExternal).toHaveBeenCalledWith(format.runtime!.downloadUrl);
    expect(prepare).not.toHaveBeenCalled();
  });
  it("uses the shared ZIP picker, format-local compiler and host commit in order", async () => {
    const { onInstalled, onReload } = view();
    await selectAndAccept();
    fireEvent.click(screen.getByRole("button", { name: "Import and install" }));
    await screen.findByText("SDK installed. Close this dialog to preview the model.");
    expect(pick).toHaveBeenCalledWith(expect.objectContaining({ extensions: [".zip"] }));
    const input = { source_path: "C:/Downloads/sdk.zip", accepted_license: true };
    expect(prepare).toHaveBeenCalledWith("demo", input);
    expect(compile).toHaveBeenCalledWith({ opaque: true }, expect.any(AbortSignal));
    expect(install).toHaveBeenCalledWith("demo", { ...input, compiled: "compiled" });
    expect(onInstalled).toHaveBeenCalledOnce();
    expect(onReload).not.toHaveBeenCalled();
  });
  it("reloads the page instead of remounting models that may still use cached fallback SDK/Core", async () => {
    const { onInstalled, onReload } = view({
      ...format,
      runtime: { ...format.runtime!, reloadAfterInstall: true },
    });
    await selectAndAccept();
    expect(screen.getByText(/Unsaved changes will be lost/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import, install and reload" }));
    await waitFor(() => expect(onReload).toHaveBeenCalledOnce());
    expect(install).toHaveBeenCalledOnce();
    expect(onInstalled).not.toHaveBeenCalled();
  });
  it.each([new Error("Disk full"), { installed: false }])(
    "never reloads after an unsuccessful installation: %j",
    async (failure) => {
      if (failure instanceof Error) install.mockRejectedValueOnce(failure);
      else install.mockResolvedValueOnce(failure);
      const { onInstalled, onReload } = view({
        ...format,
        runtime: { ...format.runtime!, reloadAfterInstall: true },
      });
      await selectAndAccept();
      fireEvent.click(screen.getByRole("button", { name: "Import, install and reload" }));
      await screen.findByRole("alert");
      expect(onReload).not.toHaveBeenCalled();
      expect(onInstalled).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Import, install and reload" })).toBeEnabled();
    },
  );
  it("reports invalid ZIPs and allows retry without committing", async () => {
    prepare.mockRejectedValueOnce(new Error("Wrong SDK version"));
    view();
    await selectAndAccept();
    fireEvent.click(screen.getByRole("button", { name: "Import and install" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong SDK version");
    expect(compile).not.toHaveBeenCalled();
    expect(install).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Import and install" })).toBeEnabled();
  });
  it("blocks dismissal during install and does not claim success on failed commit", async () => {
    let reject!: (error: Error) => void;
    install.mockImplementationOnce(
      () =>
        new Promise((_resolve, fail) => {
          reject = fail;
        }),
    );
    const { onInstalled } = view();
    await selectAndAccept();
    fireEvent.click(screen.getByRole("button", { name: "Import and install" }));
    await screen.findByText("Saving SDK…");
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    reject(new Error("Disk full"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Disk full");
    expect(onInstalled).not.toHaveBeenCalled();
  });
  it("does not install again when the pinned SDK is already installed", async () => {
    status.mockResolvedValueOnce({ installed: true });
    const { onReload } = view({ ...format, runtime: { ...format.runtime!, reloadAfterInstall: true } });
    await screen.findByText("SDK installed. Close this dialog to preview the model.");
    expect(screen.queryByRole("button", { name: "Import, install and reload" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(onReload).not.toHaveBeenCalled();
  });
});
