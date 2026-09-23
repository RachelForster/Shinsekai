import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MediaAutoLabelProgressDialog } from "../../../features/media-auto-label/MediaAutoLabelProgressDialog";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { ImageAutoLabelResult, TaskSnapshot } from "../../../shared/platform/types";

const task: TaskSnapshot<ImageAutoLabelResult> = {
  completedItems: 0,
  createdAt: 1,
  id: "task-label",
  kind: "vision-character-smart-label",
  logs: ["正在准备视觉模型"],
  message: "正在准备视觉模型并智能标注第 1/3 张图片…",
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

    expect(screen.getByRole("dialog", { name: "Smart-labeling progress" })).toBeInTheDocument();
    expect(screen.getByText("0/3 · 0%")).toBeInTheDocument();
    expect(screen.getByText(/正在准备视觉模型并智能标注第 1\/3 张图片/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Smart labeling in progress" })).toBeDisabled();
  });
});
