import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "../../../shared/ui/ErrorBoundary";

function BrokenChild() {
  throw new Error("render failed");
  return null;
}

describe("ErrorBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders children while no error is thrown", () => {
    render(
      <ErrorBoundary>
        <span>正常内容</span>
      </ErrorBoundary>,
    );

    expect(screen.getByText("正常内容")).toBeInTheDocument();
  });

  it("renders fallback UI and reports render errors", () => {
    const onError = vi.fn();
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ErrorBoundary onError={onError}>
        <BrokenChild />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("界面发生错误");
    expect(screen.getByText("render failed")).toBeInTheDocument();
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("can reset the fallback and retry rendering", () => {
    let shouldThrow = true;
    function FlakyChild() {
      if (shouldThrow) {
        throw new Error("first render failed");
      }
      return <span>恢复内容</span>;
    }
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ErrorBoundary>
        <FlakyChild />
      </ErrorBoundary>,
    );

    expect(screen.getByText("first render failed")).toBeInTheDocument();
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(screen.getByText("恢复内容")).toBeInTheDocument();
  });
});
