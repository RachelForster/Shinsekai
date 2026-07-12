import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MediaAutoLabelProgressDialog } from "../../../features/media-auto-label/MediaAutoLabelProgressDialog";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { ImageAutoLabelResult, TaskSnapshot } from "../../../shared/platform/types";

const task: TaskSnapshot<ImageAutoLabelResult> = {
  completedItems: 0,
  createdAt: 1,
  id: "task-label",
  kind: "moondream-character-auto-label",
  logs: ["正在加载 Moondream 模型"],
  message: "正在加载 Moondream 模型并准备标注第 1/3 张图片…",
  phase: "loading-model",
  progress: 0,
  result: null,
  status: "running",
  title: "label",
  totalItems: 3,
  updatedAt: 1,
};

describe("MediaAutoLabelProgressDialog", () => {
  it("shows model loading state and current item progress", () => {
    render(
      <I18nProvider language="en">
        <MediaAutoLabelProgressDialog onClose={vi.fn()} open pending result={null} task={task} />
      </I18nProvider>,
    );

    expect(screen.getByRole("dialog", { name: "Moondream labeling progress" })).toBeInTheDocument();
    expect(screen.getByText("0/3 · 0%")).toBeInTheDocument();
    expect(screen.getByText(/正在加载 Moondream 模型并准备标注第 1\/3 张图片/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Labeling in progress" })).toBeDisabled();
  });
});
