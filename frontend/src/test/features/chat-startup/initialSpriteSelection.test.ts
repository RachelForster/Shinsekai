import { describe, expect, it } from "vitest";

import { compatibleInitialSpritePath, initialSpriteOwner } from "../../../features/chat-startup/initialSpriteSelection";

const characters = [
  { name: "Nanami", sprites: [{ path: "C:/Sprites/Nanami/Idle.PNG" }] },
  { name: "Junko", sprites: [{ path: "C:/Sprites/Junko/Idle.PNG" }] },
];

describe("initial sprite selection", () => {
  it.each([
    {
      expected: "c:\\sprites\\nanami\\idle.png",
      path: " c:\\sprites\\nanami\\idle.png ",
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
