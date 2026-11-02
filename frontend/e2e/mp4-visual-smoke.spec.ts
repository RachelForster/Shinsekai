import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

if (process.platform === "win32") test.use({ channel: "msedge" });

test("decodes, loops and pauses MP4 visual assets without interfering with other layers", async ({ page }) => {
  test.setTimeout(90_000);
  const bytes = await readFile(new URL("./fixtures/visual.mp4", import.meta.url));
  const gifBytes = await readFile(new URL("./fixtures/portrait.gif", import.meta.url));
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/media?*", (route) => {
    const path = new URL(route.request().url()).searchParams.get("path");
    if (path === "broken.mp4") return route.fulfill({ status: 404 });
    return route.fulfill({
      body: path === "portrait.gif" ? gifBytes : bytes,
      contentType: path === "portrait.gif" ? "image/gif" : "video/mp4",
    });
  });
  await page.goto("/e2e/fixtures/mp4-smoke.html");
  const background = page.locator("#background video");
  const sprite = page.locator("#sprite video");
  const cover = page.locator("#covers video");
  const portrait = page.locator("#portrait video");
  await expect.poll(() => background.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(0.2);
  await expect.poll(() => sprite.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(0.2);
  await expect.poll(() => portrait.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(0.2);
  await expect(portrait).toHaveCSS("width", "240px");
  await expect(portrait).toHaveCSS("height", "480px");
  expect(await portrait.evaluate((video: HTMLVideoElement) => video.muted && video.loop && video.playsInline)).toBe(
    true,
  );
  expect(
    await sprite.evaluate((video: HTMLVideoElement) => ({
      width: video.videoWidth,
      height: video.videoHeight,
      muted: video.muted,
      inline: video.playsInline,
      loop: video.loop,
    })),
  ).toEqual({ width: 64, height: 128, muted: true, inline: true, loop: true });
  await expect(page.locator("#sprite .character-visual__static-frame")).toHaveCSS("aspect-ratio", "0.5 / 1");
  await expect.poll(() => cover.evaluate((video: HTMLVideoElement) => video.readyState)).toBeGreaterThanOrEqual(2);
  expect(await cover.evaluate((video: HTMLVideoElement) => video.paused && video.currentTime < 0.01)).toBe(true);

  // Exercise a real loop boundary, not only the HTML loop attribute.
  await background.evaluate((video: HTMLVideoElement) => {
    video.currentTime = video.duration - 0.1;
  });
  await expect.poll(() => background.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeLessThan(0.5);
  await page.getByRole("button", { name: "Hide layers" }).click();
  await expect.poll(() => background.evaluate((video: HTMLVideoElement) => video.paused)).toBe(true);
  await expect.poll(() => sprite.evaluate((video: HTMLVideoElement) => video.paused)).toBe(true);
  await expect.poll(() => portrait.evaluate((video: HTMLVideoElement) => video.paused)).toBe(true);
  await page.getByRole("button", { name: "Show layers" }).click();
  await expect.poll(() => sprite.evaluate((video: HTMLVideoElement) => video.paused)).toBe(false);
  await expect.poll(() => portrait.evaluate((video: HTMLVideoElement) => video.paused)).toBe(false);

  await page.getByRole("button", { name: "Use image" }).click();
  await expect(page.locator("#background img")).toBeVisible();
  await expect(page.locator("#sprite img")).toBeVisible();
  await expect(page.locator("#portrait img")).toBeVisible();
  await expect(portrait).toHaveCount(0);
  await expect(background).toHaveCount(0);
  await page.getByRole("button", { name: "Use MP4" }).click();
  await expect.poll(() => sprite.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(0.2);
  await expect.poll(() => portrait.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(0.2);
  await page.getByRole("button", { name: "Use GIF portrait" }).click();
  const animatedPortrait = page.locator("#portrait img");
  await expect(animatedPortrait).toBeVisible();
  const portraitFrame = page.locator("#portrait");
  const firstFrame = await portraitFrame.screenshot({ animations: "allow" });
  await expect
    .poll(async () => (await portraitFrame.screenshot({ animations: "allow" })).equals(firstFrame))
    .toBe(false);
  await expect(portrait).toHaveCount(0);
  await page.getByRole("button", { name: "Break preview" }).click();
  await expect(page.getByRole("status")).toContainText("H.264 MP4");
  expect(await sprite.evaluate((video: HTMLVideoElement) => video.paused)).toBe(false);
  await page.getByRole("button", { name: "Restore preview" }).click();
  await expect
    .poll(() => page.locator("#preview video").evaluate((video: HTMLVideoElement) => video.currentTime))
    .toBeGreaterThan(0.2);
  expect(errors).toEqual([]);
});
