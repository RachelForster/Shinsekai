// @ts-expect-error -- Vitest runs in Node; the browser bundle intentionally omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const logsPageCss: string = readFileSync("src/features/logs/LogsPage.css", "utf8");

describe("logs settings page styles", () => {
  it("uses the shared settings border instead of Chat UI frame geometry", () => {
    const shellBlock = logsPageCss.split(".logs-toolbar,\n.logs-sidebar,\n.logs-viewer {")[1]?.split("}")[0] ?? "";
    const headerBlock = logsPageCss.split(".logs-header {")[1]?.split("}")[0] ?? "";
    const detailBlock = logsPageCss.split(".logs-code__detail-grid dd,\n.logs-code__raw {")[1]?.split("}")[0] ?? "";
    const primaryButtonBlock = logsPageCss.split(".logs-page .button--primary {")[1]?.split("}")[0] ?? "";

    expect(shellBlock).toContain("border: 1px solid var(--color-border);");
    expect(shellBlock).toContain("border-radius: var(--radius-panel);");
    expect(headerBlock).toContain("border-bottom: 1px solid var(--color-border);");
    expect(detailBlock).toContain("border: 1px solid var(--color-border);");
    expect(detailBlock).toContain("border-radius: var(--radius-control);");
    expect(detailBlock).toContain("box-shadow: none;");
    expect(detailBlock).not.toContain("--logs-detail-box-shadow");
    expect(primaryButtonBlock).toContain("color: var(--color-accent-primary);");
    expect(primaryButtonBlock).toContain("background: var(--color-accent-bg-hover);");
    expect(primaryButtonBlock).not.toContain("--chat-send");
    expect(logsPageCss).not.toContain("--chat-send-color");
    expect(logsPageCss).not.toContain("--chat-send-background");
    expect(logsPageCss).not.toContain("border-image");
  });
});
