// @ts-expect-error -- Vitest runs in Node; the browser bundle intentionally omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const logsPageCss: string = readFileSync("src/features/logs/LogsPage.css", "utf8");

describe("logs settings page styles", () => {
  it("uses the shared settings border instead of Chat UI frame geometry", () => {
    const shellBlock = logsPageCss.split(".logs-toolbar,\n.logs-sidebar,\n.logs-viewer {")[1]?.split("}")[0] ?? "";
    const headerBlock = logsPageCss.split(".logs-header {")[1]?.split("}")[0] ?? "";

    expect(shellBlock).toContain("border: 1px solid var(--color-border);");
    expect(shellBlock).toContain("border-radius: var(--radius-panel);");
    expect(headerBlock).toContain("border-bottom: 1px solid var(--color-border);");
    expect(logsPageCss).not.toContain("border-image");
  });
});
