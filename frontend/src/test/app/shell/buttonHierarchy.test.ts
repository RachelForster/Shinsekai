// @vitest-environment node
// @ts-expect-error -- Vitest runs in Node; the browser bundle intentionally omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const shellCss: string = readFileSync("src/app/shell/shell.css", "utf8");
const desktopAdaptCss: string = readFileSync("src/app/shell/desktop-adapt.css", "utf8");
const mobileAdaptCss: string = readFileSync("src/app/shell/mobile-adapt.css", "utf8");

describe("shell and M3 adapt button hierarchy", () => {
  it("keeps shell.css button base rules zero-specificity and excludes ghost/default buttons from accent fills", () => {
    expect(shellCss).not.toContain(".content-outlet .button:not(.button--danger):not(.input-layer *)");
    expect(shellCss).not.toContain("body:has(.app-shell) .dialog .button:not(.button--danger)");
    expect(shellCss).toContain(":where(.content-outlet, body:has(.app-shell) .dialog) :where(.button--primary)");
    expect(shellCss).toContain(":where(.content-outlet, body:has(.app-shell) .dialog) :where(.button--ghost)");

    const ghostBlock =
      shellCss
        .split(":where(.content-outlet, body:has(.app-shell) .dialog) :where(.button--ghost):not(.input-layer *) {")[1]
        ?.split("}")[0] ?? "";
    expect(ghostBlock).toContain("border-color: transparent;");
    expect(ghostBlock).toContain("background: transparent;");
    expect(ghostBlock).toContain("box-shadow: none;");
  });

  it("defines distinct transparent ghost and soft danger pill styles on desktop", () => {
    const ghostBlock =
      desktopAdaptCss.split(":is(.app-shell, .dialog, .desktop-runtime) .button--ghost {")[1]?.split("}")[0] ?? "";
    const dangerBlock =
      desktopAdaptCss.split(":is(.app-shell, .dialog, .desktop-runtime) .button--danger {")[1]?.split("}")[0] ?? "";
    const iconBlock = desktopAdaptCss.split(":is(.app-shell, .dialog) .icon-button {")[1]?.split("}")[0] ?? "";

    expect(ghostBlock).toContain("border-color: transparent;");
    expect(ghostBlock).toContain("background: transparent;");
    expect(ghostBlock).toContain("box-shadow: none;");

    expect(dangerBlock).toContain("border-color: var(--color-danger-border);");
    expect(dangerBlock).toContain("color: var(--color-danger);");
    expect(dangerBlock).toContain("background: var(--color-danger-bg);");
    expect(dangerBlock).toContain("box-shadow: none;");

    expect(iconBlock).toContain("box-shadow: none;");
    expect(desktopAdaptCss).not.toContain(".app-shell .plugin-card__actions .button--ghost");
  });

  it("defines distinct transparent ghost and soft danger pill styles on mobile", () => {
    const ghostBlock =
      mobileAdaptCss.split(".app-shell .button--ghost,\n  .dialog .button--ghost {")[1]?.split("}")[0] ?? "";
    const dangerBlock =
      mobileAdaptCss.split(".app-shell .button--danger,\n  .dialog .button--danger {")[1]?.split("}")[0] ?? "";
    const iconBlock =
      mobileAdaptCss.split(".app-shell .icon-button,\n  .dialog .icon-button {")[1]?.split("}")[0] ?? "";

    expect(ghostBlock).toContain("border-color: transparent;");
    expect(ghostBlock).toContain("background: transparent;");
    expect(ghostBlock).toContain("box-shadow: none;");

    expect(dangerBlock).toContain("border-color: var(--color-danger-border);");
    expect(dangerBlock).toContain("color: var(--color-danger);");
    expect(dangerBlock).toContain("background: var(--color-danger-bg);");
    expect(dangerBlock).toContain("box-shadow: none;");

    expect(iconBlock).toContain("box-shadow: none;");
  });

  it("keeps primary styling for chat workspace continue buttons and normal badges", () => {
    expect(desktopAdaptCss).not.toContain(".app-shell .conversation-card__actions .button--primary");
    expect(mobileAdaptCss).not.toContain(".app-shell .conversation-card__actions .button--primary");

    for (const css of [desktopAdaptCss, mobileAdaptCss]) {
      const badgeBlock =
        css.split(".app-shell .conversation-type-badge:not(.conversation-type-badge--story) {")[1]?.split("}")[0] ?? "";
      expect(badgeBlock).toContain("border-color: var(--m3-primary-container-border);");
      expect(badgeBlock).toContain("color: var(--m3-on-primary-container);");
      expect(badgeBlock).toContain("background: var(--m3-primary-container);");
    }
  });
});
