import { readFile } from "node:fs/promises";
import { basename, dirname, extname, relative, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import type { MmdControls, MmdState } from "../src/modules/character-visual/adapters/mmd/state";
import type { AvatarSession } from "../src/modules/character-visual/contracts";

const source = process.env.SHINSEKAI_PMX_MODEL;
if (process.platform === "win32") test.use({ channel: "msedge" });
test.skip(!source, "Set SHINSEKAI_PMX_MODEL to a locally licensed PMX; model assets are never checked in.");

test("renders a local PMX with bound mouth and blink morphs", async ({ page }) => {
  test.setTimeout(180_000);
  const entry = resolve(source!);
  const root = dirname(entry);
  const requested: string[] = [];
  await page.route("**/api/avatar/file?*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.searchParams.get("path")?.replaceAll("\\", "/") ?? "";
    const target = resolve(root, path);
    const rest = relative(root, target);
    if (!path || rest.startsWith("..") || rest.includes(":")) return route.fulfill({ status: 403 });
    requested.push(path);
    const body = await readFile(target);
    const contentType =
      { ".png": "image/png", ".bmp": "image/bmp", ".tga": "image/x-tga" }[extname(target).toLowerCase()] ??
      "application/octet-stream";
    await route.fulfill({ status: 200, body, contentType });
  });
  await page.goto(`/e2e/fixtures/mmd-smoke.html?source=${encodeURIComponent(entry)}`);
  await expect(page.locator("#status")).toContainText('"capabilities"', { timeout: 120_000 });
  const status = JSON.parse((await page.locator("#status").textContent())!);
  expect(status.bindings.mouthMorph).toBeTruthy();
  expect(status.bindings.blinkMorph).toBeTruthy();
  expect(status.capabilities.mouth).toBe(true);
  expect(status.capabilities.blink).toBe(true);
  expect(requested).toContain(basename(entry));
  expect(requested.some((path) => path.toLowerCase().endsWith(".png"))).toBe(true);
  // Use real browser input: canceling pointerdown suppresses its compatibility
  // mousedown, so a synthetic fireEvent.mouseDown cannot catch broken host drag.
  await page.locator("#model canvas").click();
  expect(
    await page.evaluate(
      () => (window as unknown as { mmdSmoke: { hostInput: { mouseDowns: number } } }).mmdSmoke.hostInput.mouseDowns,
    ),
  ).toBe(1);
  const painted = await page.locator("#model canvas").evaluate((canvas: HTMLCanvasElement) => {
    const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    if (!gl) return 0;
    const pixels = new Uint8Array(canvas.width * canvas.height * 4);
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let count = 0;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 0) count++;
    return count;
  });
  expect(painted).toBeGreaterThan(1000);
  if (process.env.SHINSEKAI_MMD_SCREENSHOT) await page.screenshot({ path: process.env.SHINSEKAI_MMD_SCREENSHOT });
  const mouthChangedPixels = await page.evaluate(async () => {
    const canvas = document.querySelector("#model canvas") as HTMLCanvasElement;
    const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    if (!gl) return 0;
    const before = new Uint8Array(canvas.width * canvas.height * 4);
    const after = new Uint8Array(before.length);
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, before);
    (
      window as unknown as { mmdSmoke: { session: { setMouthOpen(value: number): void } } }
    ).mmdSmoke.session.setMouthOpen(1);
    await new Promise((done) => setTimeout(done, 300));
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, after);
    let changed = 0;
    for (let i = 0; i < before.length; i += 4)
      if (
        Math.abs(before[i] - after[i]) +
          Math.abs(before[i + 1] - after[i + 1]) +
          Math.abs(before[i + 2] - after[i + 2]) >
        30
      )
        changed++;
    return changed;
  });
  expect(mouthChangedPixels).toBeGreaterThan(50);
  const cameraResult = await page.evaluate(async () => {
    const { session } = (window as unknown as { mmdSmoke: { session: AvatarSession<MmdState, MmdControls> } }).mmdSmoke;
    const initial = session.readState();
    const signal = new AbortController().signal;
    await session.apply(initial, "edit", signal);
    await new Promise((done) => setTimeout(done, 100));
    const canvas = document.querySelector("#model canvas") as HTMLCanvasElement;
    const before = canvas.toDataURL();
    const camera = { yaw: 35, pitch: 10, zoom: 1.5, panX: 0.1, panY: -0.1 };
    await session.apply({ ...initial, camera }, "edit", signal);
    await new Promise((done) => setTimeout(done, 100));
    const changed = before !== canvas.toDataURL();
    session.resize(400, 700);
    const saved = JSON.parse(JSON.stringify(session.readState()));
    await session.apply(initial, "restore", signal);
    await session.apply(saved, "restore", signal);
    const restored = session.readState().camera;
    await session.apply(initial, "restore", signal);
    session.resize(600, 700);
    return { changed, restored, camera };
  });
  expect(cameraResult.changed).toBe(true);
  expect(cameraResult.restored).toEqual(cameraResult.camera);

  const headMotion = await page.evaluate(async () => {
    const { session, routeVoice, readHeadMatrix } = (
      window as unknown as {
        mmdSmoke: {
          session: AvatarSession<MmdState, MmdControls>;
          routeVoice(value: number): void;
          readHeadMatrix(): number[];
        };
      }
    ).mmdSmoke;
    const state = { ...session.readState(), mouthMorph: "", blinkMorph: "" };
    await session.apply(state, "restore", new AbortController().signal);
    routeVoice(0);
    const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
    await wait(200);
    const baseline = readHeadMatrix();
    routeVoice(0.8);
    await wait(600);
    const talking = readHeadMatrix();
    const preserved = JSON.stringify(state) === JSON.stringify(session.readState());
    routeVoice(0);
    await wait(3000);
    const stopped = readHeadMatrix();
    await session.apply(state, "edit", new AbortController().signal);
    routeVoice(1);
    await wait(300);
    const editing = readHeadMatrix();
    await session.apply(state, "restore", new AbortController().signal);
    return { baseline, talking, stopped, editing, preserved };
  });
  const difference = (a: number[], b: number[]) => Math.max(...a.map((value, index) => Math.abs(value - b[index])));
  expect(headMotion.baseline).toHaveLength(16);
  expect(difference(headMotion.baseline, headMotion.talking)).toBeGreaterThan(0.001);
  expect(difference(headMotion.baseline, headMotion.stopped)).toBeLessThan(0.00001);
  expect(difference(headMotion.baseline, headMotion.editing)).toBeLessThan(0.00001);
  expect(headMotion.preserved).toBe(true);

  await page.emulateMedia({ reducedMotion: "reduce" });
  const reduced = await page.evaluate(async () => {
    const { routeVoice, readHeadMatrix } = (
      window as unknown as {
        mmdSmoke: { routeVoice(value: number): void; readHeadMatrix(): number[] };
      }
    ).mmdSmoke;
    routeVoice(1);
    await new Promise((done) => setTimeout(done, 300));
    return readHeadMatrix();
  });
  expect(difference(headMotion.baseline, reduced)).toBeLessThan(0.00001);
  await page.evaluate(() => {
    const { session, unbind } = (
      window as unknown as {
        mmdSmoke: { session: AvatarSession<MmdState, MmdControls>; unbind(): void };
      }
    ).mmdSmoke;
    unbind();
    session.dispose();
  });
  await expect(page.locator("#model canvas")).toHaveCount(0);
});
