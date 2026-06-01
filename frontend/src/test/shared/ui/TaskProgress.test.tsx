import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TaskProgress } from "../../../shared/ui";

describe("TaskProgress", () => {
  it("renders nothing without a task", () => {
    const { container } = render(<TaskProgress task={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("clamps progress, renders the message, and limits logs from the end", () => {
    render(
      <TaskProgress
        logLimit={2}
        task={{
          logs: ["prepare", "download", "done"],
          message: "Almost there",
          phase: "install",
          progress: 1.4,
          status: "running",
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("install");
    expect(screen.getByRole("status")).toHaveTextContent("100%");
    expect(screen.getByText("Almost there")).toBeInTheDocument();
    expect(screen.queryByText("prepare")).not.toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "download\ndone")).toBeInTheDocument();
  });

  it("uses status text when progress and message are absent", () => {
    render(<TaskProgress task={{ phase: "queued", status: "waiting" }} />);

    expect(screen.getByRole("status")).toHaveTextContent("waiting");
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });
});
