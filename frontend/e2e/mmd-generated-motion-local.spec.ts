import { readFile } from "node:fs/promises";
import { basename, dirname, extname, relative, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import type { MmdState } from "../src/modules/character-visual/adapters/mmd/state";
import type { AvatarSession } from "../src/modules/character-visual/contracts";

const source = process.env.SHINSEKAI_PMX_MODEL;
const generated = process.env.SHINSEKAI_GENERATED_VMD_BASE64;
const action = process.env.SHINSEKAI_GENERATED_ACTION ?? "nod";
if (process.platform === "win32") test.use({ channel: "msedge" });
test.skip(!source || !generated, "Set a local PMX and an in-memory backend-generated VMD clip.");

test("plays a backend-generated short motion on the actual PMX rig", async ({ page }) => {
  test.setTimeout(120_000);
  const entry = resolve(source!);
  const root = dirname(entry);
  const motionPath = "__smoke__/generated.vmd";
  await page.route("**/api/avatar/file?*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.searchParams.get("path")?.replaceAll("\\", "/") ?? "";
    if (path === motionPath) {
      return route.fulfill({ body: Buffer.from(generated!, "base64"), contentType: "application/octet-stream" });
    }
    const target = resolve(root, path);
    const rest = relative(root, target);
    if (!path || rest.startsWith("..") || rest.includes(":")) return route.fulfill({ status: 403 });
    const body = await readFile(target);
    const contentType =
      { ".png": "image/png", ".bmp": "image/bmp", ".tga": "image/x-tga" }[extname(target).toLowerCase()] ??
      "application/octet-stream";
    await route.fulfill({ status: 200, body, contentType });
  });
  await page.goto(`/e2e/fixtures/mmd-smoke.html?source=${encodeURIComponent(entry)}`);
  await expect(page.locator("#status")).toContainText('"capabilities"', { timeout: 90_000 });
  const result = await page.evaluate(async (path) => {
    const smoke = (
      window as unknown as {
        mmdSmoke: {
          session: AvatarSession<MmdState, unknown>;
          readHeadMatrix(): number[];
          readBoneScreenPosition(name: string): number[];
          readRestBoneScreenPosition(name: string): number[];
        };
      }
    ).mmdSmoke;
    const signal = new AbortController().signal;
    const neutral = smoke.session.readState();
    await smoke.session.apply(neutral, "edit", signal);
    await new Promise((done) => setTimeout(done, 150));
    const before = smoke.readHeadMatrix();
    const wristNames = ["左手首", "右手首"];
    const idleWrists = wristNames.map((name) => smoke.readBoneScreenPosition(name));
    const tPoseWrists = wristNames.map((name) => smoke.readRestBoneScreenPosition(name));
    await smoke.session.apply({ ...neutral, motion: path, motionBase: "resting" }, "play", signal);
    await new Promise((done) => setTimeout(done, 600));
    const during = smoke.readHeadMatrix();
    const actionWrists = wristNames.map((name) => smoke.readBoneScreenPosition(name));
    await new Promise((done) => setTimeout(done, 1800));
    const finalWrists = wristNames.map((name) => smoke.readBoneScreenPosition(name));
    return {
      before,
      during,
      motion: smoke.session.readState().motion,
      idleWrists,
      tPoseWrists,
      actionWrists,
      finalWrists,
    };
  }, motionPath);
  expect(result.before).toHaveLength(16);
  expect(result.during).toHaveLength(16);
  expect(result.motion).toBe(motionPath);
  for (let side = 0; side < 2; side++) {
    expect(result.idleWrists[side]).toHaveLength(2);
    expect(Math.abs(result.idleWrists[side][1] - result.tPoseWrists[side][1])).toBeGreaterThan(5);
    expect(Math.abs(result.finalWrists[side][1] - result.idleWrists[side][1])).toBeLessThan(10);
  }
  if (action === "wave") {
    expect(Math.abs(result.actionWrists[1][1] - result.idleWrists[1][1])).toBeGreaterThan(5);
    expect(Math.abs(result.actionWrists[0][1] - result.idleWrists[0][1])).toBeLessThan(10);
  } else {
    expect(
      result.before.reduce((total, value, index) => total + Math.abs(value - result.during[index]), 0),
    ).toBeGreaterThan(0.05);
    for (let side = 0; side < 2; side++)
      expect(Math.abs(result.actionWrists[side][1] - result.idleWrists[side][1])).toBeLessThan(10);
  }
  expect(basename(entry).toLowerCase()).toMatch(/\.pmx$/);
});
