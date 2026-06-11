import { describe, expect, it } from "vitest";

import {
  buildDialogTypewriterSource,
  renderDialogTypewriterFrame,
} from "../features/chat-stage/dialogTypewriter";

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
});
