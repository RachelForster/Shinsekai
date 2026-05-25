import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../shared/i18n/I18nProvider";
import { AlertDialog, FilePicker } from "../shared/ui";

const mockPlatform = vi.hoisted(() => ({
  files: {
    browse: vi.fn(),
  },
}));

vi.mock("../shared/platform/platform", () => ({
  getPlatform: () => mockPlatform,
}));

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
    mockPlatform.files.browse.mockResolvedValue({
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

    render(
      <I18nProvider language="zh_CN">
        <FilePicker multiple onPathsChange={onPathsChange} pickLabel="选择素材" value="" />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByLabelText("选择素材"));

    const first = await screen.findByText("a.png");
    const second = await screen.findByText("b.png");
    fireEvent.click(first.closest("tr")!);
    fireEvent.click(second.closest("tr")!);
    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    expect(onPathsChange).toHaveBeenCalledWith(["/tmp/a.png", "/tmp/b.png"]);
    expect(mockPlatform.files.browse).toHaveBeenCalledWith({ path: "", showHidden: false });
  });

  it("opens parent folders from the address breadcrumbs", async () => {
    mockPlatform.files.browse.mockResolvedValueOnce({
      cwd: "/home/shinsekai/project/data/config",
      entries: [],
      parent: "/home/shinsekai/project/data",
      roots: [{ label: "Shinsekai", path: "/home/shinsekai/project" }],
    });

    render(
      <I18nProvider language="zh_CN">
        <FilePicker pickLabel="选择路径" value="" />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByLabelText("选择路径"));

    const dataCrumb = await screen.findByRole("button", { name: "data" });
    fireEvent.click(dataCrumb);

    await waitFor(() => {
      expect(mockPlatform.files.browse).toHaveBeenLastCalledWith({
        path: "/home/shinsekai/project/data",
        showHidden: false,
      });
    });
  });

  it("selects the full address when clicking the blank address area", async () => {
    const cwd = "/home/shinsekai/project/data/config";
    mockPlatform.files.browse.mockResolvedValueOnce({
      cwd,
      entries: [],
      parent: "/home/shinsekai/project/data",
      roots: [{ label: "Shinsekai", path: "/home/shinsekai/project" }],
    });

    render(
      <I18nProvider language="zh_CN">
        <FilePicker pickLabel="选择路径" value="" />
      </I18nProvider>,
    );

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
