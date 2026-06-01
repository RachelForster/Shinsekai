import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QueryErrorState } from "../../../shared/ui/QueryErrorState";

describe("QueryErrorState", () => {
  it("renders error messages and retry actions", () => {
    const onRetry = vi.fn();

    render(
      <QueryErrorState error={new Error("Network unavailable")} onRetry={onRetry} retryLabel="重试" title="加载失败" />,
    );

    expect(screen.getByText("加载失败")).toBeInTheDocument();
    expect(screen.getByText("Network unavailable")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("falls back to body text for non-error values", () => {
    render(<QueryErrorState body="稍后再试" error="bad response" retryLabel="重试" title="加载失败" />);

    expect(screen.getByText("稍后再试")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
