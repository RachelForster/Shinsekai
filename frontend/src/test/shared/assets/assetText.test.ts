import { describe, expect, it } from "vitest";

import { baseName, numberedTags, tagContents } from "../../../shared/assets/assetText";

describe("asset text helpers", () => {
  it("extracts file names from POSIX and Windows paths", () => {
    expect(baseName("/home/user/assets/Sprite01.webp")).toBe("Sprite01.webp");
    expect(baseName("C:\\Users\\Myo\\Music\\theme.ogg")).toBe("theme.ogg");
    expect(baseName("readme.md")).toBe("readme.md");
    expect(baseName("/home/user/assets/")).toBe("/home/user/assets/");
  });

  it("extracts tag content after full-width or ASCII separators", () => {
    expect(
      tagContents(["立绘 1： 开心", "Sprite 2: angry", "no separator", "", "ignored： value"].join("\n"), 4),
    ).toEqual(["开心", "angry", "no separator", "value"]);
  });

  it("pads missing tag rows with empty strings", () => {
    expect(tagContents("背景 1：校门", 3)).toEqual(["校门", "", ""]);
  });

  it("formats numbered tag blocks with the expected trailing newline", () => {
    expect(numberedTags("背景", ["校门", "教室"])).toBe("背景 1：校门\n背景 2：教室\n");
    expect(numberedTags("背景", [])).toBe("");
  });
});
