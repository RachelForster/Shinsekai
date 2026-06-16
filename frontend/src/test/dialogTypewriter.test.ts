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

  it("sanitizes unsafe html before typewriter rendering", () => {
    const source = buildDialogTypewriterSource({
      html: [
        `<p onclick="steal()">`,
        `<b style="color:#fff;background-image:url(javascript:steal())">Mio</b>: Hello`,
        `<img src=x onerror="steal()">`,
        `<script>steal()</script>`,
        `<a href="javascript:steal()">link</a>`,
        `<iframe src="https://example.test"></iframe>`,
        `</p>`,
      ].join(""),
      text: "Mio: Hello link",
    });

    expect(source.fullHtml).toContain("Mio");
    expect(source.fullHtml).toContain("Hello");
    expect(source.fullHtml).toContain("link");
    expect(source.fullHtml).not.toContain("onclick");
    expect(source.fullHtml).not.toContain("onerror");
    expect(source.fullHtml).not.toContain("<img");
    expect(source.fullHtml).not.toContain("<script");
    expect(source.fullHtml).not.toContain("<iframe");
    expect(source.fullHtml).not.toContain("javascript:");
    expect(source.fullHtml).not.toContain("background-image");
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

  it("keeps right-to-left reversal inside each original line", () => {
    const source = buildDialogTypewriterSource({
      html: "<p>alpha beta<br>gamma delta</p>",
      text: "alpha beta\ngamma delta",
    });

    expect(source.fullRtlHtml).toBe("<p>beta alpha<br>delta gamma</p>");
    expect(renderDialogTypewriterFrame(source, source.totalRtlCharacters, "rtl")).toEqual({
      html: "<p>beta alpha<br>delta gamma</p>",
      text: "beta alpha\ndelta gamma",
    });
  });

  it("keeps mixed inline html on the original line when rendering right-to-left", () => {
    const source = buildDialogTypewriterSource({
      html: "<p>你好 <strong>traveler</strong> <em>world</em><br><span>再见 alpha</span></p>",
      text: "你好 traveler world\n再见 alpha",
    });

    expect(source.fullRtlHtml).toBe("<p><em>world</em> <strong>traveler</strong> 好你<br><span>alpha 见再</span></p>");
    expect(source.totalRtlCharacters).toBe(7);
    expect(renderDialogTypewriterFrame(source, 5, "rtl")).toEqual({
      html: "<p><em>world</em> <strong>traveler</strong> 好你<br><span>alpha</span></p>",
      text: "world traveler 好你\nalpha",
    });
  });

  it("reuses cached typewriter sources for identical raw input", () => {
    const input = {
      characterName: "Mio",
      html: "<p><b>Mio</b>: Hello <strong>world</strong></p>",
      text: "Mio: Hello world",
    };

    expect(buildDialogTypewriterSource(input)).toBe(buildDialogTypewriterSource(input));
  });
});
