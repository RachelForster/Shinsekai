import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TaskProgress } from "../../../shared/ui";

describe("TaskProgress", () => {
  it("renders nothing without a task", () => {
    const { container } = render(<TaskProgress task={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("clamps progress and shows recent logs", () => {
    render(
      <TaskProgress
        logLimit={2}
        task={{
          logs: ["first", "second", "third"],
          message: "Downloading",
          phase: "running",
          progress: 1.4,
          status: "running",
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("running");
    expect(screen.getByRole("status")).toHaveTextContent("100%");
    expect(screen.getByText("Downloading")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "second\nthird")).toBeInTheDocument();
  });

  it("uses status text when progress and message are absent", () => {
    render(<TaskProgress task={{ phase: "queued", progress: null, status: "queued" }} />);

    expect(screen.getByRole("status")).toHaveTextContent("queued");
    expect(screen.queryByText("%")).not.toBeInTheDocument();
  });
});
