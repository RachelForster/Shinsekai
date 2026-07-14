// @ts-expect-error -- Vitest runs in Node; the browser bundle intentionally omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const controlsCss: string = readFileSync("src/features/chat-stage/styles/controls.css", "utf8");

describe("chat stage immersive styles", () => {
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
