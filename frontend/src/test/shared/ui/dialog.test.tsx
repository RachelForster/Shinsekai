import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { AlertDialog, FileBrowserProvider, FilePicker, PathPickerDialog } from "../../../shared/ui";

const browseFiles = vi.fn();

const { isTauriMock, openMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(() => false),
  openMock: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: openMock,
}));

vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/desktop/desktopApi")>();
  return {
    ...actual,
    isTauriDesktop: isTauriMock,
  };
});

function renderWithFileBrowser(children: ReactNode) {
  return render(children, {
    wrapper: ({ children }) => (
      <I18nProvider language="zh_CN">
        <FileBrowserProvider browse={browseFiles}>{children}</FileBrowserProvider>
      </I18nProvider>
    ),
  });
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
    isTauriMock.mockReturnValue(false);
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

describe("FilePicker on the Tauri desktop", () => {
  beforeEach(() => {
    isTauriMock.mockReturnValue(true);
    openMock.mockReset();
    browseFiles.mockResolvedValue({
      cwd: "/tmp",
      entries: [],
      parent: "/",
      roots: [],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("opens the OS-native file dialog and reports the picked path", async () => {
    const onPathChange = vi.fn();
    openMock.mockResolvedValueOnce("C:/assets/mio.png");

    renderWithFileBrowser(<FilePicker onPathChange={onPathChange} pickLabel="选择素材" value="" />);

    fireEvent.click(screen.getByLabelText("选择素材"));

    await waitFor(() => {
      expect(onPathChange).toHaveBeenCalledWith("C:/assets/mio.png");
    });
    expect(openMock).toHaveBeenCalledWith(expect.objectContaining({ directory: false, multiple: false }));
    expect(browseFiles).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "选择素材" })).not.toBeInTheDocument();
  });

  it("opens a directory dialog for directory mode", async () => {
    const onPathChange = vi.fn();
    openMock.mockResolvedValueOnce("D:/models/asr");

    renderWithFileBrowser(
      <FilePicker onPathChange={onPathChange} pickLabel="选择目录" pickerMode="directory" value="" />,
    );

    fireEvent.click(screen.getByLabelText("选择目录"));

    await waitFor(() => {
      expect(onPathChange).toHaveBeenCalledWith("D:/models/asr");
    });
    expect(openMock).toHaveBeenCalledWith(expect.objectContaining({ directory: true, multiple: false }));
  });

  it("keeps one native dialog across parent renders and uses the latest selection callback", async () => {
    let resolvePick!: (paths: string[]) => void;
    openMock.mockImplementationOnce(
      () =>
        new Promise<string[]>((resolve) => {
          resolvePick = resolve;
        }),
    );
    const onPathsChange = vi.fn();
    const onUpdatedPathsChange = vi.fn();
    const picker = (onChange: (paths: string[]) => void) => (
      <FilePicker
        acceptedExtensions={[".char", ".cha"]}
        multiple
        onPathsChange={onChange}
        pickLabel="导入人物"
        value=""
      />
    );
    const { rerender } = renderWithFileBrowser(picker(onPathsChange));

    fireEvent.click(screen.getByLabelText("导入人物"));
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    rerender(picker(onUpdatedPathsChange));
    await act(async () => {});

    expect(openMock).toHaveBeenCalledTimes(1);
    expect(openMock).toHaveBeenCalledWith(
      expect.objectContaining({
        filters: [{ extensions: ["char", "cha"], name: "char, cha" }],
        multiple: true,
      }),
    );
    await act(async () => resolvePick(["C:/characters/mio.char", "C:/characters/aki.cha"]));
    expect(onUpdatedPathsChange).toHaveBeenCalledTimes(1);
    expect(onUpdatedPathsChange).toHaveBeenCalledWith(["C:/characters/mio.char", "C:/characters/aki.cha"]);
    expect(onPathsChange).not.toHaveBeenCalled();
  });

  it("opens and handles the native dialog once when mounted open in StrictMode", async () => {
    const onClose = vi.fn();
    const onSelect = vi.fn();
    openMock.mockResolvedValue("C:/characters/mio.char");
    const picker = () => (
      <StrictMode>
        <PathPickerDialog
          acceptedExtensions={[".char", ".cha"]}
          onClose={() => onClose()}
          onSelect={(path) => onSelect(path)}
          open
          title="导入人物"
        />
      </StrictMode>
    );
    const { rerender } = renderWithFileBrowser(picker());

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("C:/characters/mio.char"));
    rerender(picker());
    await act(async () => {});

    expect(openMock).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("opens a fresh native dialog after cancellation", async () => {
    const onPathChange = vi.fn();
    openMock.mockResolvedValueOnce(null).mockResolvedValueOnce("C:/characters/mio.char");
    renderWithFileBrowser(<FilePicker onPathChange={onPathChange} pickLabel="导入人物" value="" />);

    await act(async () => fireEvent.click(screen.getByLabelText("导入人物")));
    expect(openMock).toHaveBeenCalledTimes(1);
    expect(onPathChange).not.toHaveBeenCalled();

    await act(async () => fireEvent.click(screen.getByLabelText("导入人物")));
    expect(openMock).toHaveBeenCalledTimes(2);
    expect(onPathChange).toHaveBeenCalledTimes(1);
    expect(onPathChange).toHaveBeenCalledWith("C:/characters/mio.char");
  });

  it("ignores a closed native dialog result after reopening", async () => {
    let resolveFirstPick!: (path: string) => void;
    let resolveSecondPick!: (path: string) => void;
    openMock
      .mockImplementationOnce(
        () =>
          new Promise<string>((resolve) => {
            resolveFirstPick = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<string>((resolve) => {
            resolveSecondPick = resolve;
          }),
      );
    const onClose = vi.fn();
    const onSelect = vi.fn();
    const picker = (open: boolean) => (
      <PathPickerDialog onClose={onClose} onSelect={onSelect} open={open} title="导入人物" />
    );
    const { rerender } = renderWithFileBrowser(picker(true));
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    rerender(picker(false));
    rerender(picker(true));
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(2));

    await act(async () => resolveFirstPick("C:/characters/old.char"));
    expect(onClose).not.toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
    await act(async () => resolveSecondPick("C:/characters/mio.char"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("C:/characters/mio.char");
  });

  it("keeps the value unchanged when the native dialog is cancelled", async () => {
    const onPathChange = vi.fn();
    openMock.mockResolvedValueOnce(null);

    renderWithFileBrowser(<FilePicker onPathChange={onPathChange} pickLabel="选择素材" value="" />);

    fireEvent.click(screen.getByLabelText("选择素材"));

    await waitFor(() => {
      expect(openMock).toHaveBeenCalledTimes(1);
    });
    expect(onPathChange).not.toHaveBeenCalled();
  });

  it("falls back to the in-app browser when the native dialog fails", async () => {
    const onPathChange = vi.fn();
    openMock.mockRejectedValueOnce(new Error("plugin unavailable"));

    renderWithFileBrowser(<FilePicker onPathChange={onPathChange} pickLabel="选择素材" value="" />);

    fireEvent.click(screen.getByLabelText("选择素材"));

    expect(await screen.findByRole("dialog", { name: "选择素材" })).toBeInTheDocument();
    expect(onPathChange).not.toHaveBeenCalled();
  });

  it("keeps the fallback browser open across parent renders without retrying the native dialog", async () => {
    openMock.mockRejectedValue(new Error("plugin unavailable"));
    const picker = () => <FilePicker acceptedExtensions={[".char", ".cha"]} pickLabel="导入人物" value="" />;
    const { rerender } = renderWithFileBrowser(picker());
    fireEvent.click(screen.getByLabelText("导入人物"));
    expect(await screen.findByRole("dialog", { name: "导入人物" })).toBeInTheDocument();

    rerender(picker());
    await act(async () => {});

    expect(openMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "导入人物" })).toBeInTheDocument();
  });
});
