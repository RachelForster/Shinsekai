import { test } from "@playwright/test";

test.describe("CUJ: character management", () => {
  test.skip("creates a character and reopens the saved draft", async ({ page }) => {
    // User creates a character, fills identity/personality/voice fields, saves, and reselects it.
    await page.goto("/#/settings/characters");
  });

  test.skip("manages character sprites, tags, scale, and voice text", async ({ page }) => {
    // User adds sprites, edits emotion tags, adjusts sprite scale, and edits per-sprite voice text.
    await page.goto("/#/settings/characters");
  });

  test.skip("prevents accidental destructive character actions", async ({ page }) => {
    // User attempts delete/delete-all actions and must confirm before data disappears.
    await page.goto("/#/settings/characters");
  });

  test.skip("imports and exports a character package", async ({ page }) => {
    // User exports an existing character, imports the package, and sees the imported character.
    await page.goto("/#/settings/characters");
  });
});
