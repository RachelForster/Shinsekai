// @ts-expect-error -- Vitest runs in Node; the browser bundle intentionally omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const controlsCss: string = readFileSync("src/features/chat-stage/styles/controls.css", "utf8");
const dialogLayerCss: string = readFileSync("src/features/chat-stage/styles/dialog-layer.css", "utf8");
const inputLayerCss: string = readFileSync("src/features/chat-stage/styles/input-layer.css", "utf8");
const mediaLayersCss: string = readFileSync("src/features/chat-stage/styles/media-layers.css", "utf8");
const optionsLayerCss: string = readFileSync("src/features/chat-stage/styles/options-layer.css", "utf8");
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

  it("positions sprites on absolute axes so neighboring sprites can overlap without reflow", () => {
    const layerBlock = mediaLayersCss.split(".sprite-layer {")[1]?.split("}")[0] ?? "";
    const figureBlock = mediaLayersCss.split(".sprite-layer__figure {")[1]?.split("}")[0] ?? "";
    const imageBlock = mediaLayersCss.split(".sprite-layer__image {")[2]?.split("}")[0] ?? "";

    expect(layerBlock).not.toContain("display: flex");
    expect(layerBlock).not.toContain("gap:");
    expect(figureBlock).toContain("position: absolute;");
    expect(figureBlock).toContain("inset: 0;");
    expect(imageBlock).toContain("left: var(--sprite-axis-center);");
    expect(imageBlock).toContain("translate: calc(-50%");
    expect(imageBlock).toContain("chat-stage-sprite-in 340ms ease-out");
    expect(imageBlock).toContain("chat-stage-sprite-slide 360ms");
  });

  it("renders choices as independent modern surfaces without an outer dialog frame", () => {
    const layerBlock = optionsLayerCss.split(".options-layer {")[1]?.split("}")[0] ?? "";
    const buttonBlock = optionsLayerCss.split(".options-layer__button {")[1]?.split("}")[0] ?? "";

    expect(layerBlock).toContain("border: 0;");
    expect(layerBlock).toContain("background: transparent;");
    expect(layerBlock).toContain("box-shadow: none;");
    expect(layerBlock).toContain("backdrop-filter: none;");
    // The option button intentionally has no backdrop-filter blur: filtering a
    // subtree whose ancestor animates in makes Chromium/Edge flash a bright bar for
    // a frame. (The rule's comment still mentions the word, so assert on the value.)
    expect(buttonBlock).not.toContain("backdrop-filter: blur");
    expect(buttonBlock).toContain("transform: none;");
    expect(optionsLayerCss).toContain(".options-layer__item:has(.options-layer__button:hover:not(:disabled))");
    expect(optionsLayerCss).toContain("@keyframes chat-option-enter");
  });

  it("renders component background images as filled nine-slice surfaces", () => {
    const dialogBlock = dialogLayerCss.split(".dialog-layer {")[1]?.split("}")[0] ?? "";
    const nameBlock = dialogLayerCss.split(".dialog-layer__name {")[1]?.split("}")[0] ?? "";
    const optionBlock = optionsLayerCss.split(".options-layer__button {")[1]?.split("}")[0] ?? "";
    const inputBlock = inputLayerCss.split(".input-layer {")[1]?.split("}")[0] ?? "";
    const toolbarBlock = controlsCss.split(".top-stage-tools {")[1]?.split("}")[0] ?? "";
    const dialogToolbarBlock = controlsCss.split(".dialog-stage-controls__surface {")[1]?.split("}")[0] ?? "";

    for (const block of [dialogBlock, nameBlock, optionBlock, inputBlock, toolbarBlock, dialogToolbarBlock]) {
      expect(block).toContain("border-image-source:");
      expect(block).toMatch(/border-image-slice:\s*var\([^;]+\) fill;/);
      expect(block).toContain("border-image-repeat: stretch;");
    }

    expect(dialogBlock).not.toContain("var(--chat-dialog-background-image, none),");
    expect(nameBlock).not.toContain("var(--chat-name-background-image)");
  });
});
