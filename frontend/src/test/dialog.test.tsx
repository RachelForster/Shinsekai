import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../shared/i18n/I18nProvider";
import { AlertDialog, FileBrowserProvider, FilePicker } from "../shared/ui";

const browseFiles = vi.fn();

function renderWithFileBrowser(children: ReactNode) {
  return render(
    <I18nProvider language="zh_CN">
      <FileBrowserProvider browse={browseFiles}>{children}</FileBrowserProvider>
    </I18nProvider>,
  );
}

describe("AlertDialog", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("labels the dialog and closes on Escape", () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();

    render(
      <AlertDialog
        body="确认执行操作？"
        confirmLabel="执行"
        onCancel={onCancel}
        onConfirm={onConfirm}
        open
        title="确认操作"
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "确认操作" });
    expect(dialog).toHaveAttribute("aria-modal", "true");

    fireEvent.keyDown(dialog, { key: "Escape" });

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("FilePicker", () => {
  beforeEach(() => {
    browseFiles.mockResolvedValue({
      cwd: "/tmp",
      entries: [
        { kind: "file", modifiedAt: 1, name: "a.png", path: "/tmp/a.png", size: 1 },
        { kind: "file", modifiedAt: 1, name: "b.png", path: "/tmp/b.png", size: 2 },
      ],
      parent: "/",
      roots: [{ label: "Shinsekai", path: "/tmp" }],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("uses the self-drawn browser for multiple file selection", async () => {
    const onPathsChange = vi.fn();

    renderWithFileBrowser(<FilePicker multiple onPathsChange={onPathsChange} pickLabel="选择素材" value="" />);

    fireEvent.click(screen.getByLabelText("选择素材"));

    const first = await screen.findByText("a.png");
    const second = await screen.findByText("b.png");
    fireEvent.click(first.closest("tr")!);
    fireEvent.click(second.closest("tr")!);
    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    expect(onPathsChange).toHaveBeenCalledWith(["/tmp/a.png", "/tmp/b.png"]);
    expect(browseFiles).toHaveBeenCalledWith({ path: "", showHidden: false });
  });

  it("uses an initial picker path without changing the empty input value", async () => {
    const onPathChange = vi.fn();

    renderWithFileBrowser(
      <FilePicker
        onPathChange={onPathChange}
        pickLabel="Select local plugin directory"
        pickerInitialPath="plugins"
        pickerMode="directory"
        readOnly
        value=""
      />,
    );

    fireEvent.click(screen.getByLabelText("Select local plugin directory"));

    await waitFor(() => {
      expect(browseFiles).toHaveBeenCalledWith({ path: "plugins", showHidden: false });
    });
    expect(screen.getByRole("button", { name: "Select local plugin directory" })).toBeInTheDocument();
  });

  it("opens parent folders from the address breadcrumbs", async () => {
    browseFiles.mockResolvedValueOnce({
      cwd: "/home/shinsekai/project/data/config",
      entries: [],
      parent: "/home/shinsekai/project/data",
      roots: [{ label: "Shinsekai", path: "/home/shinsekai/project" }],
    });

    renderWithFileBrowser(<FilePicker pickLabel="选择路径" value="" />);

    fireEvent.click(screen.getByLabelText("选择路径"));

    const dataCrumb = await screen.findByRole("button", { name: "data" });
    fireEvent.click(dataCrumb);

    await waitFor(() => {
      expect(browseFiles).toHaveBeenLastCalledWith({
        path: "/home/shinsekai/project/data",
        showHidden: false,
      });
    });
  });

  it("selects the full address when clicking the blank address area", async () => {
    const cwd = "/home/shinsekai/project/data/config";
    browseFiles.mockResolvedValueOnce({
      cwd,
      entries: [],
      parent: "/home/shinsekai/project/data",
      roots: [{ label: "Shinsekai", path: "/home/shinsekai/project" }],
    });

    renderWithFileBrowser(<FilePicker pickLabel="选择路径" value="" />);

    fireEvent.click(screen.getByLabelText("选择路径"));
    fireEvent.click(await screen.findByRole("group", { name: cwd }));

    const input = await screen.findByDisplayValue(cwd);
    await waitFor(() => {
      expect(input).toHaveFocus();
      expect((input as HTMLInputElement).selectionStart).toBe(0);
      expect((input as HTMLInputElement).selectionEnd).toBe(cwd.length);
    });
  });
});
