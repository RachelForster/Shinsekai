import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToolsDrawer } from "../../../features/tools/ToolsDrawer";
import { I18nProvider } from "../../../shared/i18n";

vi.mock("../../../features/tools/ToolsPage", () => ({
  ToolsPanelContent: ({ embedded }: { embedded?: boolean }) => (
    <div data-embedded={embedded ? "true" : "false"}>Prompt tools</div>
  ),
}));

function renderDrawer(open: boolean, onClose = vi.fn()) {
  render(
    <I18nProvider language="en">
      <ToolsDrawer onClose={onClose} open={open} />
    </I18nProvider>,
  );
  return { onClose };
}

describe("ToolsDrawer", () => {
  it("renders nothing while closed", () => {
    renderDrawer(false);
    expect(screen.queryByRole("dialog", { name: "Tools" })).not.toBeInTheDocument();
  });

  it("renders embedded tools and closes from escape, scrim, and header control", () => {
    const { onClose } = renderDrawer(true);

    expect(screen.getByRole("dialog", { name: "Tools" })).toBeInTheDocument();
    expect(screen.getByText("Prompt tools")).toHaveAttribute("data-embedded", "true");

    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[1]);

    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
