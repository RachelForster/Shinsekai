import { expect, test } from "@playwright/test";
import type { AvatarSession } from "../src/modules/character-visual/contracts";
import type { L2DControls, L2DState } from "../src/modules/character-visual/adapters/l2d/state";

if (process.platform === "win32") test.use({ channel: "msedge" });
test.skip(
  !process.env.SHINSEKAI_L2D_SMOKE,
  "Requires locally authorized Cubism Core and Haru; no licensed assets in Git.",
);

interface Smoke {
  session: AvatarSession<L2DState, L2DControls>;
  readHeadAngles(): number[];
  routeVoice(value: number): void;
  unbind(): void;
}
declare global {
  interface Window {
    l2dSmoke: Smoke;
  }
}

test("Haru speech moves rendered head parameters without changing saved state", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/e2e/fixtures/l2d-smoke.html");
  await expect(page.locator("#status")).toContainText('"capabilities"', { timeout: 20000 });
  const result = await page.evaluate(async () => {
    const { session, readHeadAngles, routeVoice } = window.l2dSmoke;
    const state = session.readState();
    const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
    await wait(100);
    const baseline = readHeadAngles();
    routeVoice(0.8);
    await wait(600);
    const talking = readHeadAngles();
    const preserved = JSON.stringify(session.readState()) === JSON.stringify(state);
    routeVoice(0);
    await wait(3000);
    const stopped = readHeadAngles();
    await session.apply(state, "edit", new AbortController().signal);
    routeVoice(1);
    await wait(200);
    const editing = readHeadAngles();
    await session.apply(state, "restore", new AbortController().signal);
    return { baseline, talking, stopped, editing, preserved };
  });
  const difference = (a: number[], b: number[]) => Math.max(...a.map((value, index) => Math.abs(value - b[index])));
  expect(result.baseline).toHaveLength(3);
  expect(difference(result.baseline, result.talking)).toBeGreaterThan(0.1);
  expect(difference(result.baseline, result.stopped)).toBeLessThan(0.00001);
  expect(difference(result.baseline, result.editing)).toBeLessThan(0.00001);
  expect(result.preserved).toBe(true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const reduced = await page.evaluate(async () => {
    window.l2dSmoke.routeVoice(1);
    await new Promise((done) => setTimeout(done, 200));
    return window.l2dSmoke.readHeadAngles();
  });
  expect(difference(result.baseline, reduced)).toBeLessThan(0.00001);
  await page.evaluate(() => {
    window.l2dSmoke.unbind();
    window.l2dSmoke.session.dispose();
  });
  await expect(page.locator("#model canvas")).toHaveCount(0);
  expect(errors).toEqual([]);
});
