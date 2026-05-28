import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../shared/i18n/I18nProvider";
import { FileManager, normalizeFileExtensions } from "../shared/ui/FileManager";

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
  });

  it("normalizes accepted file extensions", () => {
    expect(normalizeFileExtensions(["png", ".JPG", "  webp  ", ""])).toEqual([".png", ".jpg", ".webp"]);
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
});
