import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ToastProvider, useToast } from "../../../shared/ui";

function ToastTrigger({ message, title }: { message?: string; title: string }) {
  const { showToast } = useToast();
  return <button onClick={() => showToast({ kind: "success", message, title })}>触发</button>;
}

describe("Toast", () => {
  it("shows a toast title after triggering", async () => {
    render(
      <ToastProvider>
        <ToastTrigger title="操作成功" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => {
      expect(screen.getByText("操作成功")).toBeInTheDocument();
    });
  });

  it("shows a toast with title and message", async () => {
    render(
      <ToastProvider>
        <ToastTrigger message="已保存 3 个文件" title="保存完成" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => {
      expect(screen.getByText("保存完成")).toBeInTheDocument();
      expect(screen.getByText("已保存 3 个文件")).toBeInTheDocument();
    });
  });
});
