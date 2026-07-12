import { describe, expect, it } from "vitest";

import {
  compatibleInitialSpritePath,
  initialSpriteOwner,
  spritePathsAreCaseSensitive,
} from "../../../features/chat-startup/initialSpriteSelection";

const characters = [
  { name: "Nanami", sprites: [{ path: "C:/Sprites/Nanami/Idle.PNG" }] },
  { name: "Junko", sprites: [{ path: "C:/Sprites/Junko/Idle.PNG" }] },
];

describe("initial sprite selection", () => {
  it.each([
    {
      expected: "C:\\Sprites\\Nanami\\Idle.PNG",
      path: " C:\\Sprites\\Nanami\\Idle.PNG ",
      preserveUnknown: true,
      selectedCharacters: ["Nanami"],
    },
    {
      expected: "C:/SPRITES/NANAMI/IDLE.png",
      path: "C:/SPRITES/NANAMI/IDLE.png",
      preserveUnknown: true,
      selectedCharacters: ["Nanami"],
    },
    {
      expected: "",
      path: "C:/Sprites/Junko/Idle.PNG",
      preserveUnknown: true,
      selectedCharacters: ["Nanami"],
    },
    {
      expected: "D:/external/custom.png",
      path: " D:/external/custom.png ",
      preserveUnknown: true,
      selectedCharacters: ["Nanami"],
    },
    {
      expected: "",
      path: "D:/external/custom.png",
      preserveUnknown: false,
      selectedCharacters: ["Nanami"],
    },
    { expected: "", path: "   ", preserveUnknown: true, selectedCharacters: ["Nanami"] },
  ])("normalizes compatible paths without changing the retained value", (testCase) => {
    expect(compatibleInitialSpritePath({ characters, ...testCase })).toBe(testCase.expected);
  });

  it("keeps case-distinct sprite paths assigned to their exact owners", () => {
    const caseDistinctCharacters = [
      { name: "Upper", sprites: [{ path: "sprites/Hero.png" }] },
      { name: "Lower", sprites: [{ path: "sprites/hero.png" }] },
    ];

    expect(initialSpriteOwner("sprites/Hero.png", caseDistinctCharacters, { caseSensitive: true })).toBe("Upper");
    expect(initialSpriteOwner("sprites/hero.png", caseDistinctCharacters, { caseSensitive: true })).toBe("Lower");
    expect(
      compatibleInitialSpritePath({
        caseSensitive: true,
        characters: caseDistinctCharacters,
        path: "sprites/hero.png",
        selectedCharacters: ["Lower"],
      }),
    ).toBe("sprites/hero.png");
    expect(
      compatibleInitialSpritePath({
        caseSensitive: true,
        characters: caseDistinctCharacters,
        path: "sprites/hero.png",
        selectedCharacters: ["Upper"],
      }),
    ).toBe("");
  });

  it("matches Windows path casing with the same semantics as os.path.normcase", () => {
    expect(initialSpriteOwner("c:\\sprites\\nanami\\idle.png", characters, { caseSensitive: false })).toBe("Nanami");
    expect(
      compatibleInitialSpritePath({
        caseSensitive: false,
        characters,
        path: "c:\\sprites\\nanami\\idle.png",
        preserveUnknown: false,
        selectedCharacters: ["Nanami"],
      }),
    ).toBe("c:\\sprites\\nanami\\idle.png");
    expect(
      compatibleInitialSpritePath({
        caseSensitive: false,
        characters,
        path: "c:\\sprites\\nanami\\idle.png",
        preserveUnknown: false,
        selectedCharacters: ["Junko"],
      }),
    ).toBe("");
  });

  it.each([
    ["Win32", false],
    ["Windows", false],
    ["Linux x86_64", true],
    ["MacIntel", true],
  ])("derives host path casing for %s", (platform, expected) => {
    expect(spritePathsAreCaseSensitive(platform)).toBe(expected);
  });

  it("handles empty and malformed character collections without matching an owner", () => {
    expect(
      compatibleInitialSpritePath({
        characters: [],
        path: "D:/external/custom.png",
        selectedCharacters: [],
      }),
    ).toBe("D:/external/custom.png");
    expect(
      initialSpriteOwner("C:/Sprites/Nanami/Idle.PNG", [
        null,
        { name: "Broken", sprites: null },
      ] as unknown as typeof characters),
    ).toBeUndefined();
  });
});
