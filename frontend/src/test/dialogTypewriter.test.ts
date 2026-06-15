import { describe, expect, it } from "vitest";

import { buildDialogTypewriterSource, renderDialogTypewriterFrame } from "../features/chat-stage/dialogTypewriter";

describe("dialog typewriter helpers", () => {
  it("strips the duplicated speaker prefix from html and text sources", () => {
    const source = buildDialogTypewriterSource({
      characterName: "Mio",
      html: "<p><b style='color:#fff;'>Mio</b>：Hello<br>world</p>",
      text: "Mio：Hello\nworld",
    });

    expect(source.fullHtml).toBe("<p>Hello<br>world</p>");
    expect(source.fullText).toBe("Hello\nworld");
    expect(source.totalCharacters).toBe(10);
  });

  it("renders html frames without breaking markup", () => {
    const source = buildDialogTypewriterSource({
      characterName: "Mio",
      html: "<p>Hello<br>world</p>",
      text: "Hello\nworld",
    });

    expect(renderDialogTypewriterFrame(source, 0)).toEqual({ html: "<p></p>", text: "" });
    expect(renderDialogTypewriterFrame(source, 5)).toEqual({ html: "<p>Hello</p>", text: "Hello" });
    expect(renderDialogTypewriterFrame(source, 7)).toEqual({ html: "<p>Hello<br>wo</p>", text: "Hello\nwo" });
    expect(renderDialogTypewriterFrame(source, 10)).toEqual({
      html: "<p>Hello<br>world</p>",
      text: "Hello\nworld",
    });
  });

  it("does not render leading markdown line breaks before visible text starts", () => {
    const source = buildDialogTypewriterSource({
      text: "\nHello",
    });

    expect(source.fullHtml).toBe("<br>Hello");
    expect(source.totalCharacters).toBe(5);
    expect(renderDialogTypewriterFrame(source, 0)).toEqual({ html: "", text: "" });
    expect(renderDialogTypewriterFrame(source, 1)).toEqual({ html: "<br>H", text: "H" });
  });

  it("reveals right-to-left frames by Chinese characters and English words", () => {
    const source = buildDialogTypewriterSource({
      characterName: "Mio",
      html: "<p>你好 traveler world</p>",
      text: "Mio：你好 traveler world",
    });

    expect(source.totalRtlCharacters).toBe(4);
    expect(renderDialogTypewriterFrame(source, 1, "rtl")).toEqual({ html: "<p>world</p>", text: "world" });
    expect(renderDialogTypewriterFrame(source, 2, "rtl")).toEqual({
      html: "<p>world traveler</p>",
      text: "world traveler",
    });
    expect(renderDialogTypewriterFrame(source, 4, "rtl")).toEqual({
      html: "<p>world traveler 好你</p>",
      text: "world traveler 好你",
    });
  });
});
