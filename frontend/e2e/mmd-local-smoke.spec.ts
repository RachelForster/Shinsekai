import { readFile } from "node:fs/promises";
import { basename, dirname, extname, relative, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import type { MmdControls, MmdState } from "../src/modules/character-visual/adapters/mmd/state";
import type { AvatarSession } from "../src/modules/character-visual/contracts";
import { vmdBytes } from "../src/test/fixtures/mmdMotion";

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
    if (path === "__smoke__/pose.vpd") {
      return route.fulfill({
        body: "Vocaloid Pose Data file\n\nmodel.osm;\n1;\nBone0{頭\n0,0,0;\n0,0.258819,0,0.965926;\n}\n",
      });
    }
    if (path === "__smoke__/eyes.vpd") {
      return route.fulfill({
        body: "Vocaloid Pose Data file\n\nmodel.osm;\n1;\nBone0{両目\n0,0,0;\n0,0.0998334,0,0.995004;\n}\n",
      });
    }
    if (path === "__smoke__/hair.vpd") {
      return route.fulfill({
        body: "Vocaloid Pose Data file\n\nmodel.osm;\n1;\nBone0{サイドC_左01\n0,0,0;\n0,0,0.0499792,0.9987503;\n}\n",
      });
    }
    if (path === "__smoke__/nod.vmd") {
      // Shift-JIS encoding of 頭; the motion is synthetic, not a redistributed asset.
      return route.fulfill({ body: Buffer.from(vmdBytes(new Uint8Array([0x93, 0xaa]))) });
    }
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
  await expect
    .poll(
      () =>
        page.locator("#model canvas").evaluate((canvas: HTMLCanvasElement) => {
          const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
          if (!gl) return 0;
          const pixels = new Uint8Array(canvas.width * canvas.height * 4);
          gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
          let count = 0;
          for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 0) count++;
          return count;
        }),
      { timeout: 30_000 },
    )
    .toBeGreaterThan(1000);
  const arms = await page.evaluate(() => {
    const { readBoneScreenPosition, readRestBoneScreenPosition } = (
      window as unknown as {
        mmdSmoke: {
          readBoneScreenPosition(name: string): number[];
          readRestBoneScreenPosition(name: string): number[];
        };
      }
    ).mmdSmoke;
    return ["左手首", "右手首"].map((name) => ({
      resting: readBoneScreenPosition(name),
      original: readRestBoneScreenPosition(name),
    }));
  });
  for (const arm of arms)
    if (arm.resting.length) {
      expect(arm.resting[1] - arm.original[1]).toBeGreaterThan(20);
      expect(Math.abs(arm.resting[0] - 300)).toBeLessThan(Math.abs(arm.original[0] - 300) - 20);
    }
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
    const { session, routeVoice, readHeadMatrix, readChestMatrix } = (
      window as unknown as {
        mmdSmoke: {
          session: AvatarSession<MmdState, MmdControls>;
          routeVoice(value: number): void;
          readHeadMatrix(): number[];
          readChestMatrix(): number[];
        };
      }
    ).mmdSmoke;
    const state = { ...session.readState(), mouthMorph: "", blinkMorph: "" };
    routeVoice(0);
    const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
    await session.apply(state, "edit", new AbortController().signal);
    await wait(100);
    const neutral = readHeadMatrix();
    await session.apply(state, "restore", new AbortController().signal);
    await wait(600);
    const baseline = readHeadMatrix();
    const chestBaseline = readChestMatrix();
    await wait(1200);
    const breathing = readHeadMatrix();
    const chestBreathing = readChestMatrix();
    routeVoice(0.8);
    await wait(600);
    const talking = readHeadMatrix();
    const preserved = JSON.stringify(state) === JSON.stringify(session.readState());
    routeVoice(0);
    await wait(3000);
    await session.apply(state, "edit", new AbortController().signal);
    routeVoice(1);
    await wait(300);
    const editing = readHeadMatrix();
    routeVoice(0);
    await session.apply(state, "restore", new AbortController().signal);
    return { neutral, baseline, breathing, chestBaseline, chestBreathing, talking, editing, preserved };
  });
  const difference = (a: number[], b: number[]) => Math.max(...a.map((value, index) => Math.abs(value - b[index])));
  expect(headMotion.baseline).toHaveLength(16);
  expect(difference(headMotion.baseline, headMotion.breathing)).toBeGreaterThan(0.00001);
  if (headMotion.chestBaseline.length)
    expect(difference(headMotion.chestBaseline, headMotion.chestBreathing)).toBeGreaterThan(0.00001);
  expect(difference(headMotion.baseline, headMotion.talking)).toBeGreaterThan(0.001);
  expect(difference(headMotion.neutral, headMotion.editing)).toBeLessThan(0.00001);
  expect(headMotion.preserved).toBe(true);

  // A changed matrix can still move entirely in depth. Measure the default
  // front view across a full breath so the idle motion is actually visible.
  const idleVisibility = await page.evaluate(async () => {
    const { readHeadScreenPosition, readChestScreenPosition } = (
      window as unknown as {
        mmdSmoke: {
          readHeadScreenPosition(): number[];
          readChestScreenPosition(): number[];
        };
      }
    ).mmdSmoke;
    const head: number[] = [];
    const chest: number[] = [];
    for (let i = 0; i < 40; i++) {
      await new Promise((done) => setTimeout(done, 150));
      head.push(readHeadScreenPosition()[1]);
      chest.push(readChestScreenPosition()[1]);
    }
    return { head: Math.max(...head) - Math.min(...head), chest: Math.max(...chest) - Math.min(...chest) };
  });
  if (headMotion.chestBaseline.length) {
    expect(idleVisibility.head).toBeGreaterThan(0.5);
    expect(idleVisibility.chest).toBeGreaterThan(0.5);
  }
  console.log("MMD idle screen displacement (px):", idleVisibility);

  const gaze = await page.evaluate(async () => {
    const { session, eyeNames, readEyeSurfacePosition, readEyeRotation, readHeadScreenPosition, readHeadYaw } = (
      window as unknown as {
        mmdSmoke: {
          session: AvatarSession<MmdState, MmdControls>;
          eyeNames: string[];
          readEyeSurfacePosition(name: string): number[];
          readEyeRotation(name: string): number[];
          readHeadScreenPosition(): number[];
          readHeadYaw(): number;
        };
      }
    ).mmdSmoke;
    if (eyeNames.length !== 2) return null;
    const signal = new AbortController().signal;
    const state = { ...session.readState(), mouthMorph: "", blinkMorph: "" };
    const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
    session.setAttention?.("idle");
    await session.apply(state, "edit", signal);
    await wait(150);
    await session.apply(state, "restore", signal);
    session.setAttention?.("responding");
    await wait(150);
    const neutral = eyeNames.map(readEyeRotation);
    const baseX = eyeNames.map((name) => readEyeSurfacePosition(name)[0] - readHeadScreenPosition()[0]);
    const headBaseline = readHeadYaw();
    session.setAttention?.("thinking");
    const started = performance.now();
    while (performance.now() - started < 2500) {
      await new Promise(requestAnimationFrame);
      const eye = readEyeRotation(eyeNames[0]);
      if (Math.max(...eye.map((value, i) => Math.abs(value - neutral[0][i]))) > 0.006) break;
    }
    const earlyHead = readHeadYaw();
    await wait(650);
    const followingHead = readHeadYaw();
    const thought = eyeNames.map(readEyeRotation);
    const displacement = eyeNames.map(
      (name, i) => readEyeSurfacePosition(name)[0] - readHeadScreenPosition()[0] - baseX[i],
    );
    session.setAttention?.("responding");
    await wait(1000);
    const returned = eyeNames.map(readEyeRotation);
    session.setAttention?.("idle");
    // Authored shared-eye tracks must win even when holding a completed VPD pose.
    const hasController = eyeNames.includes("左目") && eyeNames.includes("右目");
    let authoredBefore: number[][] = [],
      authoredAfter: number[][] = [];
    if (hasController) {
      await session.apply({ ...state, motion: "__smoke__/eyes.vpd" }, "restore", signal);
      await wait(150);
      authoredBefore = eyeNames.map(readEyeRotation);
      session.setAttention?.("thinking");
      await wait(1100);
      authoredAfter = eyeNames.map(readEyeRotation);
    }
    session.setAttention?.("idle");
    await session.apply(state, "restore", signal);
    return {
      neutral,
      thought,
      returned,
      displacement,
      authoredBefore,
      authoredAfter,
      saved: session.readState(),
      state,
      headBaseline,
      earlyHead,
      followingHead,
    };
  });
  if (gaze) {
    for (let i = 0; i < 2; i++) {
      expect(difference(gaze.neutral[i], gaze.thought[i])).toBeGreaterThan(0.01);
      expect(Math.abs(gaze.displacement[i])).toBeGreaterThan(0.15);
      expect(difference(gaze.neutral[i], gaze.returned[i])).toBeLessThan(0.001);
      if (gaze.authoredBefore.length)
        expect(difference(gaze.authoredBefore[i], gaze.authoredAfter[i])).toBeLessThan(0.00001);
    }
    expect(Math.sign(gaze.displacement[0])).toBe(Math.sign(gaze.displacement[1]));
    expect(gaze.saved).toEqual(gaze.state);
    expect(Math.abs(gaze.earlyHead - gaze.headBaseline)).toBeLessThan(0.002);
    expect(Math.abs(gaze.followingHead - gaze.headBaseline)).toBeGreaterThan(0.004);
    console.log("MMD thinking eye surface displacement (px):", gaze.displacement);
  }

  const contextualBlink = await page.evaluate(async (blinkMorph: string) => {
    const { session, routeSpeechEvent, readMorphWeight } = (
      window as unknown as {
        mmdSmoke: {
          session: AvatarSession<MmdState, MmdControls>;
          routeSpeechEvent(event: "started" | "finished"): void;
          readMorphWeight(name: string): number;
        };
      }
    ).mmdSmoke;
    const signal = new AbortController().signal;
    const state = { ...session.readState(), blinkMorph };
    const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
    await session.apply(state, "edit", signal);
    await wait(100);
    await session.apply(state, "restore", signal);
    await wait(150);
    routeSpeechEvent("finished");
    const weights: number[] = [];
    for (let i = 0; i < 75; i++) {
      await wait(20);
      weights.push(readMorphWeight(blinkMorph));
    }
    await session.apply({ ...state, blinkMorph: "" }, "restore", signal);
    return { peak: Math.max(...weights), ending: weights.at(-1) };
  }, status.bindings.blinkMorph);
  expect(contextualBlink.peak).toBeGreaterThan(0.9);
  expect(contextualBlink.ending).toBe(0);

  const presets = await page.evaluate(async () => {
    const { session, readHeadMatrix, readHeadPose } = (
      window as unknown as {
        mmdSmoke: {
          session: AvatarSession<MmdState, MmdControls>;
          readHeadMatrix(): number[];
          readHeadPose(): number[];
        };
      }
    ).mmdSmoke;
    const signal = new AbortController().signal;
    const base = { ...session.readState(), mouthMorph: "", blinkMorph: "" };
    const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
    await session.apply(base, "edit", signal);
    await wait(100);
    const neutral = readHeadMatrix();
    await session.apply({ ...base, motion: "__smoke__/pose.vpd" }, "play", signal);
    await wait(400);
    const pose = readHeadMatrix();
    await session.apply({ ...base, motion: "__smoke__/nod.vmd" }, "play", signal);
    await wait(400);
    const middle = readHeadMatrix();
    await wait(1000);
    const end = readHeadMatrix();
    const endPose = readHeadPose();
    await session.apply({ ...base, motion: "__smoke__/nod.vmd" }, "restore", signal);
    await wait(100);
    const restoredPose = readHeadPose();
    await session.apply(base, "edit", signal);
    await wait(100);
    const cleared = readHeadMatrix();
    await session.apply(base, "restore", signal);
    return {
      neutral,
      pose,
      middle,
      end,
      endPose,
      restoredPose,
      cleared,
      canvases: document.querySelectorAll("#model canvas").length,
    };
  });
  expect(difference(presets.neutral, presets.pose)).toBeGreaterThan(0.01);
  expect(difference(presets.middle, presets.end)).toBeGreaterThan(0.01);
  // Compare persistent inputs: held poses now keep breathing in the rendered matrices.
  expect(presets.endPose).toEqual(presets.restoredPose);
  expect(difference(presets.neutral, presets.cleared)).toBeLessThan(0.00001);
  expect(presets.canvases).toBe(1);
  expect(requested.filter((path) => path === "__smoke__/nod.vmd")).toHaveLength(1);

  const wind = await page.evaluate(async () => {
    const { session, routeVoice, readSurfacePosition } = (
      window as unknown as {
        mmdSmoke: {
          session: AvatarSession<MmdState, MmdControls>;
          routeVoice(value: number): void;
          readSurfacePosition(name: string, relativeTo: string): number[];
        };
      }
    ).mmdSmoke;
    const probes = [
      { name: "サイドC_左02", anchor: "頭", minimum: 1.6 },
      { name: "サイドC_右02", anchor: "頭", minimum: 1.6 },
      { name: "スカート_4_0", anchor: "下半身", minimum: 0.5 },
      { name: "スカート_4_9", anchor: "下半身", minimum: 0.5 },
    ];
    const state = { ...session.readState(), mouthMorph: "", blinkMorph: "" };
    const signal = new AbortController().signal;
    const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
    routeVoice(0);
    session.setAttention?.("responding");
    await session.apply(state, "edit", signal);
    await wait(150);
    const original = probes.map(({ name, anchor }) => readSurfacePosition(name, anchor));
    // These probes calibrate Nanami; other locally supplied rigs still run the generic smoke checks.
    if (original.some((point) => point.length !== 2)) {
      await session.apply(state, "restore", signal);
      session.setAttention?.("idle");
      return null;
    }
    await session.apply(state, "restore", signal);
    const offsets: number[][] = [];
    for (let i = 0; i < 60; i++) {
      await wait(200);
      offsets.push(probes.map(({ name, anchor }, index) => readSurfacePosition(name, anchor)[0] - original[index][0]));
    }
    const displacement = probes.map(({ name, minimum }, i) => ({
      name,
      minimum,
      peak: Math.max(...offsets.map((sample) => Math.abs(sample[i]))),
    }));
    await session.apply({ ...state, motion: "__smoke__/hair.vpd" }, "restore", signal);
    await wait(150);
    const authored = probes.map(({ name, anchor }) => readSurfacePosition(name, anchor)[0]);
    const authoredOffsets: number[] = [];
    for (let i = 0; i < 30; i++) {
      await wait(150);
      authoredOffsets.push(
        ...probes.map(({ name, anchor }, index) => Math.abs(readSurfacePosition(name, anchor)[0] - authored[index])),
      );
    }
    await session.apply(state, "restore", signal);
    session.setAttention?.("idle");
    return { displacement, authoredDrift: Math.max(...authoredOffsets), preserved: session.readState(), state };
  });
  if (wind) {
    console.log("MMD breeze surface displacement (px):", wind.displacement);
    for (const { peak, minimum } of wind.displacement) expect(peak).toBeGreaterThan(minimum);
    expect(wind.authoredDrift).toBeLessThan(0.02);
    expect(wind.preserved).toEqual(wind.state);
  }

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
  expect(difference(headMotion.neutral, reduced)).toBeLessThan(0.00001);
  if (process.env.SHINSEKAI_MMD_SCREENSHOT) await page.screenshot({ path: process.env.SHINSEKAI_MMD_SCREENSHOT });
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
