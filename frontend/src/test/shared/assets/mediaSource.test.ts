import { describe, expect, it } from "vitest";

import { classifyMediaSource } from "../../../shared/assets/mediaSource";

describe("classifyMediaSource", () => {
  it("does not confuse Windows drive paths with URI schemes", () => {
    expect(classifyMediaSource(String.raw`C:\Users\Mio\image.png`)).toBe("local");
    expect(classifyMediaSource("D:/Users/Mio/image.png")).toBe("local");
    expect(classifyMediaSource("C:drive-relative.png")).toBe("unsupported");
  });

  it("distinguishes supported direct URLs from unsupported schemes", () => {
    expect(classifyMediaSource("https://example.test/image.png")).toBe("direct");
    expect(classifyMediaSource("HTTPS://example.test/image.png")).toBe("direct");
    expect(classifyMediaSource("ASSET://localhost/image.png")).toBe("direct");
    expect(classifyMediaSource("Blob:https://example.test/image-id")).toBe("direct");
    expect(classifyMediaSource("DATA:image/png;base64,AA==")).toBe("direct");
    expect(classifyMediaSource("https://")).toBe("unsupported");
    expect(classifyMediaSource("https://user:secret@example.test/image.png")).toBe("unsupported");
    expect(classifyMediaSource("https://@example.test/image.png")).toBe("unsupported");
    expect(classifyMediaSource("https://:@example.test/image.png")).toBe("unsupported");
    expect(classifyMediaSource(String.raw`https://example.test\spoofed.test/image.png`)).toBe("unsupported");
    expect(classifyMediaSource("https://example.test:invalid/image.png")).toBe("unsupported");
    expect(classifyMediaSource("https://example.test:99999/image.png")).toBe("unsupported");
    expect(classifyMediaSource("https:////example.test/image.png")).toBe("unsupported");
    expect(classifyMediaSource("https://example test/image.png")).toBe("unsupported");
    expect(classifyMediaSource("https://exa%6dple.test/image.png")).toBe("unsupported");
    expect(classifyMediaSource("blob:")).toBe("unsupported");
    expect(classifyMediaSource("data:image/png;base64")).toBe("unsupported");
    expect(classifyMediaSource("asset:")).toBe("unsupported");
    expect(classifyMediaSource("asset://@localhost/image.png")).toBe("unsupported");
    expect(classifyMediaSource("asset://:@localhost/image.png")).toBe("unsupported");
    expect(classifyMediaSource(String.raw`asset://localhost\image.png`)).toBe("unsupported");
    expect(classifyMediaSource("asset://localhost:invalid/image.png")).toBe("unsupported");
    expect(classifyMediaSource("asset://local host/image.png")).toBe("unsupported");
    expect(classifyMediaSource("asset://local%68ost/image.png")).toBe("unsupported");
    expect(classifyMediaSource("/assets/system/image.png")).toBe("direct");
    expect(classifyMediaSource("/assets/system/image.png?v=1#preview")).toBe("direct");
    expect(classifyMediaSource("/assets/../api/media")).toBe("unsupported");
    expect(classifyMediaSource("/assets/%2e%2e/api/media")).toBe("unsupported");
    expect(classifyMediaSource("/assets/system%2Fimage.png")).toBe("unsupported");
    expect(classifyMediaSource("/assets/system/%ZZ.png")).toBe("unsupported");
    expect(classifyMediaSource(String.raw`/assets/system\image.png`)).toBe("unsupported");
    expect(classifyMediaSource("/assets//image.png")).toBe("unsupported");
    expect(classifyMediaSource("/assets/system/CON.png")).toBe("unsupported");
    expect(classifyMediaSource("/assets/system/image.")).toBe("unsupported");
    expect(classifyMediaSource("/assets/system/image%3Apreview.png")).toBe("unsupported");
    expect(classifyMediaSource("/Assets/system/image.png")).toBe("local");
    expect(classifyMediaSource("javascript:alert(1)")).toBe("unsupported");
    expect(classifyMediaSource("file:///tmp/image.png")).toBe("unsupported");
    expect(classifyMediaSource(" /assets/system/image.png")).toBe("unsupported");
    expect(classifyMediaSource("/assets/system/image.png\n")).toBe("unsupported");
    expect(classifyMediaSource("data/\ud800/image.png")).toBe("unsupported");
    expect(classifyMediaSource("data/image.png")).toBe("local");
    expect(classifyMediaSource("")).toBe("empty");
  });
});
