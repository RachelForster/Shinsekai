import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ExpansionPanelFlow } from "../../../shared/ui";

describe("ExpansionPanelFlow", () => {
  it("marks completed steps and routes active panel changes", () => {
    const onActiveChange = vi.fn();
    render(
      <ExpansionPanelFlow
        activeId="publish"
        items={[
          {
            body: <div>Install body</div>,
            description: "Install dependencies",
            id: "install",
            title: "Install",
          },
          {
            accent: "success",
            body: <div>Publish body</div>,
            description: "Publish plugin",
            done: true,
            id: "publish",
            title: "Publish",
          },
        ]}
        onActiveChange={onActiveChange}
        title="Plugin setup"
      />,
    );

    expect(screen.getByText("Install body").closest(".expansion-panel__region")).toHaveAttribute("hidden");
    expect(screen.getByText("Publish body")).toBeVisible();
    expect(screen.getByRole("button", { name: /Publish plugin/ })).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getByRole("button", { name: /Install dependencies/ }));
    expect(onActiveChange).toHaveBeenCalledWith("install");
  });
});
