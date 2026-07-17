import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ThemeFrame } from "../../../shared/ui";

describe("ThemeFrame", () => {
  it("aliases one surface to its own frame variables and an optional panel fallback", () => {
    const { container } = render(<ThemeFrame fallbackPrefix="logs-panel" prefix="logs-viewer" />);
    const frame = container.firstElementChild as HTMLElement;

    expect(frame).toHaveAttribute("aria-hidden", "true");
    expect(frame).toHaveAttribute("data-theme-frame", "logs-viewer");
    expect(frame.style.getPropertyValue("--theme-frame-image")).toBe(
      "var(--logs-viewer-frame-image, var(--logs-panel-frame-image, none))",
    );
    expect(frame.style.getPropertyValue("--theme-frame-width")).toBe(
      "var(--logs-viewer-frame-width, var(--logs-panel-frame-width, 0px))",
    );
  });
});
