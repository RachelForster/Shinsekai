import { readFile } from "node:fs/promises";
import { dirname, extname, relative, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import type { MmdState } from "../src/modules/character-visual/adapters/mmd/state";
import type { AvatarSession } from "../src/modules/character-visual/contracts";

const source = process.env.SHINSEKAI_PMX_MODEL;
const generated = process.env.SHINSEKAI_EMOTION_VMD_BASE64;
if (process.platform === "win32") test.use({ channel: "msedge" });
test.skip(!source || !generated, "Set a local PMX and an in-memory backend-generated emotion VMD clip.");

test("keeps real PMX arms lowered while playing a generated emotion", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const entry = resolve(source!);
  const root = dirname(entry);
  const motionPath = "__smoke__/emotion.vmd";
  await page.route("**/api/avatar/file?*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.searchParams.get("path")?.replaceAll("\\", "/") ?? "";
    if (path === motionPath)
      return route.fulfill({ body: Buffer.from(generated!, "base64"), contentType: "application/octet-stream" });
    const target = resolve(root, path);
    const rest = relative(root, target);
    if (!path || rest.startsWith("..") || rest.includes(":")) return route.fulfill({ status: 403 });
    const body = await readFile(target);
    const contentType =
      { ".png": "image/png", ".bmp": "image/bmp", ".tga": "image/x-tga" }[extname(target).toLowerCase()] ??
      "application/octet-stream";
    return route.fulfill({ status: 200, body, contentType });
  });
  await page.goto(`/e2e/fixtures/mmd-smoke.html?source=${encodeURIComponent(entry)}`);
  await expect(page.locator("#status")).toContainText('"capabilities"', { timeout: 90_000 });
  const result = await page.evaluate(async (path) => {
    const smoke = (
      window as unknown as {
        mmdSmoke: {
          session: AvatarSession<MmdState, unknown>;
          readBoneScreenPosition(name: string): number[];
          readRestBoneScreenPosition(name: string): number[];
          readHeadMatrix(): number[];
        };
      }
    ).mmdSmoke;
    const signal = new AbortController().signal;
    const neutral = smoke.session.readState();
    await smoke.session.apply({ ...neutral, motion: path, motionBase: "resting" }, "edit", signal);
    await new Promise((done) => setTimeout(done, 250));
    const wrists = ["左手首", "右手首"].map((name) => ({
      current: smoke.readBoneScreenPosition(name),
      original: smoke.readRestBoneScreenPosition(name),
    }));
    const firstHead = smoke.readHeadMatrix();
    await smoke.session.apply({ ...neutral, motion: path, motionBase: "resting" }, "play", signal);
    await new Promise((done) => setTimeout(done, 600));
    const duringHead = smoke.readHeadMatrix();
    return { wrists, firstHead, duringHead, motion: smoke.session.readState().motion };
  }, motionPath);
  expect(result.motion).toBe(motionPath);
  for (const wrist of result.wrists) {
    expect(wrist.current).toHaveLength(2);
    expect(wrist.original).toHaveLength(2);
    expect(wrist.current[1] - wrist.original[1]).toBeGreaterThan(20);
    expect(Math.abs(wrist.current[0] - 300)).toBeLessThan(Math.abs(wrist.original[0] - 300) - 20);
  }
  expect(
    result.firstHead.reduce((sum, value, index) => sum + Math.abs(value - result.duringHead[index]), 0),
  ).toBeGreaterThan(0.02);
  await page.screenshot({ path: testInfo.outputPath("mmd-emotion-denial.png") });
});
