import { describe, expect, it } from "vitest";

import {
  buildDialogTypewriterSource,
  type DialogHtmlNode,
  type DialogTypewriterSource,
  renderDialogTypewriterFrame,
  renderDialogTypewriterRichFrame,
} from "../../../features/chat-stage/dialogTypewriter";

type DialogElementNode = Extract<DialogHtmlNode, { kind: "element" }>;

function isDialogElementNode(node: DialogHtmlNode): node is DialogElementNode {
  return node.kind === "element";
}

function collectDialogElementNodes(nodes: DialogHtmlNode[]): DialogElementNode[] {
  return nodes.flatMap((node) => {
    if (!isDialogElementNode(node)) {
      return [];
    }
    return [node, ...collectDialogElementNodes(node.children)];
  });
}

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

  it("strips html speaker labels with the separator inside the bold node", () => {
    const source = buildDialogTypewriterSource({
      characterName: "Mio",
      html: "<p><b>Mio：</b>Hello</p>",
      text: "Mio：Hello",
    });

    expect(source.fullHtml).toBe("<p>Hello</p>");
    expect(source.fullText).toBe("Hello");
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

  it("returns structured html nodes for React rendering", () => {
    const source = buildDialogTypewriterSource({
      html: `<p>Hello <strong>world</strong><br><a href="https://example.test">docs</a></p>`,
      text: "Hello world\ndocs",
    });

    expect(renderDialogTypewriterRichFrame(source, source.totalCharacters)).toMatchObject({
      html: `<p>Hello <strong>world</strong><br><a href="https://example.test" rel="noreferrer" target="_blank">docs</a></p>`,
      nodes: [
        {
          children: [
            { kind: "text", text: "Hello " },
            { children: [{ kind: "text", text: "world" }], kind: "element", tag: "strong" },
            { children: [], kind: "element", tag: "br" },
            {
              attrs: { href: "https://example.test", rel: "noreferrer", target: "_blank" },
              children: [{ kind: "text", text: "docs" }],
              kind: "element",
              tag: "a",
            },
          ],
          kind: "element",
          tag: "p",
        },
      ],
      text: "Hello world\ndocs",
    });
  });

  it("sanitizes disallowed tags in rich HTML nodes", () => {
    const source = buildDialogTypewriterSource({
      html: `<p>Hello <script>alert(1)</script><iframe src="https://evil.test"></iframe><style>body{background-image:url('x')}</style></p>`,
      text: "Hello alert(1)",
    });

    const frame = renderDialogTypewriterRichFrame(source, source.totalCharacters);
    const tags = collectDialogElementNodes(frame.nodes ?? []).map((node) => node.tag);

    expect(frame.html).not.toContain("<script");
    expect(frame.html).not.toContain("<iframe");
    expect(frame.html).not.toContain("<style");
    expect(tags).not.toContain("script");
    expect(tags).not.toContain("iframe");
    expect(tags).not.toContain("style");
  });

  it("filters unsafe inline styles in rich HTML nodes", () => {
    const source = buildDialogTypewriterSource({
      html: `<p style="background-image:url('x');position:fixed;color:red;">Styled</p>`,
      text: "Styled",
    });

    const frame = renderDialogTypewriterRichFrame(source, source.totalCharacters);
    const pNode = collectDialogElementNodes(frame.nodes ?? []).find((node) => node.tag === "p");

    expect(frame.html).not.toContain("background-image");
    expect(frame.html).not.toContain("position");
    expect(frame.html).toContain("color: red");
    expect(pNode?.attrs?.style).toEqual({ color: "red" });
  });

  it("removes unsafe link schemes from rich HTML nodes", () => {
    const source = buildDialogTypewriterSource({
      html: `<p><a href="javascript:alert(1)">js link</a> <a href="data:text/plain;base64,AAAA">data link</a> <a href="https://safe.test">safe</a></p>`,
      text: "js link data link safe",
    });

    const frame = renderDialogTypewriterRichFrame(source, source.totalCharacters);
    const anchors = collectDialogElementNodes(frame.nodes ?? []).filter((node) => node.tag === "a");

    expect(frame.html).not.toContain("javascript:");
    expect(frame.html).not.toContain("data:");
    expect(anchors.map((node) => node.attrs?.href)).toEqual([undefined, undefined, "https://safe.test"]);
  });

  it("returns text nodes when no HTML source is present", () => {
    const source: DialogTypewriterSource = {
      cacheKey: "text:Hello world",
      fullRtlText: "Hello world",
      fullText: "Hello world",
      totalCharacters: 11,
      totalRtlCharacters: 11,
    };

    expect(renderDialogTypewriterRichFrame(source, source.totalCharacters)).toMatchObject({
      html: "Hello world",
      nodes: [{ kind: "text", text: "Hello world" }],
      text: "Hello world",
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
