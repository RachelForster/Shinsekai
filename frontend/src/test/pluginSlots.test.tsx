import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { normalizePluginContributions, PluginSlot } from "../shared/plugin/PluginSlot";
import type { PluginUIContribution } from "../shared/plugin/PluginSlot";

const validContribution: PluginUIContribution = {
  id: "demo.output",
  permissions: ["chat:read"],
  render: ({ title }) => <span>{title}</span>,
  slot: "chat-output",
  title: "Demo Output",
};

describe("plugin slot registry", () => {
  it("keeps only declared, unique plugin contributions", () => {
    const normalized = normalizePluginContributions([
      { ...validContribution, id: " demo.output ", title: " Demo Output " },
      { ...validContribution, id: "demo.output", title: "Duplicate" },
      { ...validContribution, id: "", title: "Missing ID" },
      { ...validContribution, id: "missing.title", title: "" },
    ]);

    expect(normalized).toHaveLength(1);
    expect(normalized[0]).toMatchObject({
      id: "demo.output",
      permissions: ["chat:read"],
      title: "Demo Output",
    });
  });

  it("renders only contributions for the requested fixed slot", () => {
    render(
      <PluginSlot
        contributions={[
          validContribution,
          {
            ...validContribution,
            id: "demo.toolbar",
            render: () => <span>Toolbar</span>,
            slot: "chat-toolbar",
            title: "Toolbar",
          },
        ]}
        slot="chat-output"
      />,
    );

    expect(screen.getByText("Demo Output")).toBeInTheDocument();
    expect(screen.queryByText("Toolbar")).not.toBeInTheDocument();
    expect(screen.getByText("Demo Output").parentElement).toHaveAttribute("data-plugin-slot", "chat-output");
  });
});
