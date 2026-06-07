import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../shared/i18n/I18nProvider";
import { FileManager, normalizeFileExtensions, normalizeFileManagerPath } from "../shared/ui/FileManager";

const browseFiles = vi.fn();

function renderFileManager(props: ComponentProps<typeof FileManager>) {
  return render(
    <I18nProvider language="zh_CN">
      <FileManager onBrowse={browseFiles} {...props} />
    </I18nProvider>,
  );
}

describe("FileManager", () => {
  beforeEach(() => {
    browseFiles.mockResolvedValue({
      cwd: "/project",
      entries: [
        { kind: "directory", modifiedAt: 1, name: "assets", path: "/project/assets" },
        { kind: "file", modifiedAt: 1, name: "hero.png", path: "/project/hero.png", size: 2048 },
        { kind: "file", modifiedAt: 1, name: "notes.txt", path: "/project/notes.txt", size: 100 },
      ],
      parent: "/",
      roots: [{ label: "Shinsekai", path: "/project" }],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("normalizes accepted file extensions", () => {
    expect(normalizeFileExtensions(["png", ".JPG", "  webp  ", ""])).toEqual([".png", ".jpg", ".webp"]);
  });

  it("normalizes Windows verbatim paths for display", () => {
    expect(normalizeFileManagerPath("\\\\?\\D:\\")).toBe("D:/");
    expect(normalizeFileManagerPath("\\\\?\\D:\\Games\\")).toBe("D:/Games/");
    expect(normalizeFileManagerPath("\\\\?\\UNC\\server\\share\\asset.png")).toBe("//server/share/asset.png");
    expect(normalizeFileManagerPath("//?/D:/")).toBe("D:/");
  });

  it("renders Windows locations without verbatim prefixes", async () => {
    browseFiles.mockResolvedValue({
      cwd: "\\\\?\\D:\\",
      entries: [{ kind: "directory", modifiedAt: 1, name: "Media", path: "\\\\?\\D:\\Media" }],
      parent: "",
      roots: [
        { label: "Data", path: "\\\\?\\D:\\data" },
        { label: "Downloads", path: "\\\\?\\C:\\Users\\Tester\\Downloads" },
        { label: "Home", path: "\\\\?\\C:\\Users\\Tester" },
        { label: "\\\\?\\D:\\", path: "\\\\?\\D:\\" },
        { label: "D:", path: "\\\\?\\D:\\" },
      ],
    });

    renderFileManager({});

    expect(await screen.findByRole("group", { name: "D:/" })).toBeInTheDocument();
    const roots = screen.getByLabelText("位置");
    expect(screen.getByRole("button", { name: "用户目录" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "数据目录" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载目录" })).toBeInTheDocument();
    expect(within(roots).getAllByRole("button", { name: "D:" })).toHaveLength(1);
    expect(screen.queryByText(/\\\\\?/)).toBeNull();

    const rootLabels = within(roots)
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(rootLabels.indexOf("数据目录")).toBeLessThan(rootLabels.indexOf("下载目录"));
    expect(rootLabels.indexOf("下载目录")).toBeLessThan(rootLabels.indexOf("用户目录"));

    fireEvent.click(screen.getByRole("button", { name: "用户目录" }));

    await waitFor(() => {
      expect(browseFiles).toHaveBeenLastCalledWith({ path: "C:/Users/Tester", showHidden: false });
    });

    fireEvent.click(screen.getByRole("button", { name: "下载目录" }));

    await waitFor(() => {
      expect(browseFiles).toHaveBeenLastCalledWith({ path: "C:/Users/Tester/Downloads", showHidden: false });
    });
  });

  it("keeps directory mode selection scoped to directories", async () => {
    const onSelectionChange = vi.fn();

    renderFileManager({ mode: "directory", onSelectionChange });

    const folder = await screen.findByText("assets");
    await waitFor(() => {
      expect(onSelectionChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          confirmPaths: ["/project"],
          cwd: "/project",
          selectedPaths: ["/project"],
        }),
      );
    });

    fireEvent.click(folder.closest("tr")!);

    await waitFor(() => {
      expect(onSelectionChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          confirmPaths: ["/project/assets"],
          cwd: "/project",
          selectedPaths: ["/project/assets"],
        }),
      );
    });
  });

  it("allows path mode to select files and directories", async () => {
    const onSelectionChange = vi.fn();

    renderFileManager({ mode: "path", onSelectionChange });

    const folder = await screen.findByText("assets");
    const file = await screen.findByText("hero.png");
    fireEvent.click(folder.closest("tr")!);

    await waitFor(() => {
      expect(onSelectionChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          confirmPaths: ["/project/assets"],
          selectedPaths: ["/project/assets"],
        }),
      );
    });

    fireEvent.click(file.closest("tr")!);

    await waitFor(() => {
      expect(onSelectionChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          confirmPaths: ["/project/hero.png"],
          selectedPaths: ["/project/hero.png"],
        }),
      );
    });
  });

  it("navigates to a typed address with Enter", async () => {
    renderFileManager({});

    fireEvent.click(await screen.findByRole("group", { name: "/project" }));
    const input = await screen.findByDisplayValue("/project");
    fireEvent.change(input, { target: { value: "/project/data" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(browseFiles).toHaveBeenLastCalledWith({ path: "/project/data", showHidden: false });
    });
  });

  it("navigates through breadcrumb buttons", async () => {
    renderFileManager({});

    await screen.findByText("hero.png");
    fireEvent.click(screen.getByRole("button", { name: "/" }));

    await waitFor(() => {
      expect(browseFiles).toHaveBeenLastCalledWith({ path: "/", showHidden: false });
    });
  });

  it("selects the full address when the address control is clicked", async () => {
    renderFileManager({});

    fireEvent.click(await screen.findByRole("group", { name: "/project" }));
    const input = await screen.findByDisplayValue("/project");

    await waitFor(() => {
      expect(input).toHaveFocus();
      expect(input).toHaveProperty("selectionStart", 0);
      expect(input).toHaveProperty("selectionEnd", "/project".length);
    });
  });

  it("reloads the current folder when hidden files are toggled", async () => {
    renderFileManager({});

    await screen.findByText("hero.png");
    fireEvent.click(screen.getByRole("button", { name: "显示隐藏文件" }));

    await waitFor(() => {
      expect(browseFiles).toHaveBeenLastCalledWith({ path: "/project", showHidden: true });
    });
  });

  it("stops showing the loading state when folder loading stalls", async () => {
    vi.useFakeTimers();
    browseFiles.mockImplementationOnce(() => new Promise(() => undefined));

    renderFileManager({});

    expect(screen.getByText("正在读取文件夹...")).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(12_000);
    });

    expect(screen.getByText("读取文件夹超时，请刷新或输入更具体的路径。")).toBeTruthy();
    expect(screen.queryByText("正在读取文件夹...")).toBeNull();
  });
});
