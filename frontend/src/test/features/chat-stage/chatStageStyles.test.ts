// @ts-expect-error -- Vitest runs in Node; the browser bundle intentionally omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const controlsCss: string = readFileSync("src/features/chat-stage/styles/controls.css", "utf8");
const themePickerCss: string = readFileSync("src/features/chat-stage/theme/chat-theme-picker.css", "utf8");

describe("chat stage immersive styles", () => {
  it("keeps the theme picker shell and scrollable body widths in sync", () => {
    const dialogBlock = themePickerCss.split(".dialog.chat-theme-picker__dialog")[1]?.split("}")[0] ?? "";
    const bodyBlock = themePickerCss.split(".chat-theme-picker__dialog-body")[1]?.split("}")[0] ?? "";

    expect(dialogBlock).toContain("width: min(960px, 100%);");
    expect(dialogBlock).toContain("overflow: hidden;");
    expect(bodyBlock).toContain("min-width: 0;");
    expect(bodyBlock).toContain("overflow: auto;");
    expect(bodyBlock).not.toContain("vw");
  });

  it("reserves enough toolbar width for standalone desktop window controls", () => {
    expect(controlsCss).toMatch(/\.top-stage-tools\s*\{[\s\S]*?--top-stage-tools-controls-width:\s*64px;/);
    expect(controlsCss).toMatch(
      /\.top-stage-tools\[data-standalone-desktop="true"\]\s*\{[\s\S]*?--top-stage-tools-controls-width:\s*160px;/,
    );
    expect(controlsCss).toMatch(
      /\.top-stage-tools:is\(:hover, :focus-within\) \.top-stage-tools__controls\s*\{[\s\S]*?max-width:\s*var\(--top-stage-tools-controls-width\);/,
    );
  });

  it("preserves standalone toolbar centering while hidden and with reduced motion", () => {
    const selector = '.top-stage-tools[data-standalone-desktop="true"][data-auto-hide="true"][data-visible="false"]';
    const transforms = controlsCss
      .split(selector)
      .slice(1)
      .map((block) => block.match(/transform:\s*([^;]+);/)?.[1])
      .filter(Boolean);

    expect(transforms).toEqual(["translateX(-50%) translateY(-8px)", "translateX(-50%)"]);
  });
});
