import { expect, test } from "@playwright/test";
import fs from "node:fs";

test.use({ channel: "msedge" });

function nodAnimation() {
  const values = new Float32Array([0, 0.5, 1, 0, 0, 0, 1, Math.sin(0.15), 0, 0, Math.cos(0.15), 0, 0, 0, 1]);
  const bin = Buffer.from(values.buffer);
  const json = Buffer.from(
    JSON.stringify({
      asset: { version: "2.0" },
      scene: 0,
      scenes: [{ nodes: [0] }],
      nodes: [
        { name: "hips", translation: [0, 1, 0], children: [1] },
        { name: "head", translation: [0, 0.6, 0] },
      ],
      buffers: [{ byteLength: bin.length }],
      bufferViews: [
        { buffer: 0, byteOffset: 0, byteLength: 12 },
        { buffer: 0, byteOffset: 12, byteLength: 48 },
      ],
      accessors: [
        { bufferView: 0, componentType: 5126, count: 3, type: "SCALAR", min: [0], max: [1] },
        { bufferView: 1, componentType: 5126, count: 3, type: "VEC4" },
      ],
      animations: [
        {
          samplers: [{ input: 0, output: 1, interpolation: "LINEAR" }],
          channels: [{ sampler: 0, target: { node: 1, path: "rotation" } }],
        },
      ],
      extensionsUsed: ["VRMC_vrm_animation"],
      extensions: {
        VRMC_vrm_animation: { specVersion: "1.0", humanoid: { humanBones: { hips: { node: 0 }, head: { node: 1 } } } },
      },
    }),
  );
  const padded = Buffer.concat([json, Buffer.alloc((4 - (json.length % 4)) % 4, 32)]);
  const header = Buffer.alloc(20);
  header.write("glTF");
  header.writeUInt32LE(2, 4);
  header.writeUInt32LE(28 + padded.length + bin.length, 8);
  header.writeUInt32LE(padded.length, 12);
  header.writeUInt32LE(0x4e4f534a, 16);
  const binHeader = Buffer.alloc(8);
  binHeader.writeUInt32LE(bin.length);
  binHeader.writeUInt32LE(0x004e4942, 4);
  return Buffer.concat([header, padded, binHeader, bin]);
}

test("VRM renders, applies a state, plays VRMA, and disposes", async ({ page }) => {
  const model = process.env.SHINSEKAI_TEST_VRM;
  test.skip(!model, "Set SHINSEKAI_TEST_VRM to a local test model");
  await page.route("**/test-model.vrm", (route) =>
    route.fulfill({ contentType: "model/gltf-binary", body: fs.readFileSync(model!) }),
  );
  await page.route("**/test-motion.vrma", (route) =>
    route.fulfill({ contentType: "model/gltf-binary", body: nodAnimation() }),
  );
  await page.goto("/");
  const result = await page.evaluate(async () => {
    document.body.innerHTML = '<div id="vrm-test" style="width:600px;height:700px"></div>';
    const { create } = await import(/* @vite-ignore */ "/src/modules/character-visual/adapters/vrm/module.ts");
    const controller = new AbortController();
    const element = document.getElementById("vrm-test")!;
    const session = await create(
      {
        element,
        modelUrl: "/test-model.vrm",
        assetUrl: () => "/test-motion.vrma",
        reportError: (error: Error) => {
          throw error;
        },
      },
      controller.signal,
    );
    session.resize(600, 700);
    const expression = session.controls.expressions.includes("happy") ? "happy" : session.controls.expressions[0];
    if (!expression) throw new Error("The model has no expression controls");
    await session.apply({ expressions: { [expression]: 0.8 }, bones: {}, motion: "" }, "edit", controller.signal);
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const canvas = element.querySelector("canvas")!;
    const output = document.createElement("canvas");
    output.width = canvas.width;
    output.height = canvas.height;
    const context = output.getContext("2d")!;
    context.drawImage(canvas, 0, 0);
    const pixels = context.getImageData(0, 0, output.width, output.height).data;
    let visiblePixels = 0;
    for (let index = 3; index < pixels.length; index += 4) {
      if (pixels[index] > 0) visiblePixels++;
    }
    const saved = session.readState();
    await session.apply({ expressions: {}, bones: {}, motion: "test-motion.vrma" }, "play", controller.signal);
    // The synthetic clip lasts one second; let its finished event run before disposal.
    await new Promise((resolve) => setTimeout(resolve, 1300));
    const motionSaved = session.readState();
    session.dispose();
    session.dispose();
    return {
      visiblePixels,
      savedExpression: saved.expressions[expression],
      motion: motionSaved.motion,
      canvasCount: element.querySelectorAll("canvas").length,
    };
  });
  expect(result.visiblePixels).toBeGreaterThan(1000);
  expect(result.savedExpression).toBe(0.8);
  expect(result.motion).toBe("test-motion.vrma");
  expect(result.canvasCount).toBe(0);
});

test("VRM queues consecutive dialogue motions in order and skips failed downloads", async ({ page }) => {
  const model = process.env.SHINSEKAI_TEST_VRM;
  test.skip(!model, "Set SHINSEKAI_TEST_VRM to a local test model");
  await page.route("**/test-model.vrm", (route) =>
    route.fulfill({ contentType: "model/gltf-binary", body: fs.readFileSync(model!) }),
  );
  await page.route("**/*.vrma", async (route) => {
    if (route.request().url().includes("slow")) await new Promise((resolve) => setTimeout(resolve, 500));
    if (route.request().url().includes("broken")) return route.fulfill({ status: 500, body: "failed" });
    await route.fulfill({ contentType: "model/gltf-binary", body: nodAnimation() });
  });
  await page.goto("/");
  const result = await page.evaluate(async () => {
    const { create } = await import(/* @vite-ignore */ "/src/modules/character-visual/adapters/vrm/module.ts");
    const element = document.createElement("div");
    document.body.append(element);
    const lifetime = new AbortController();
    const session = await create(
      { element, modelUrl: "/test-model.vrm", assetUrl: (path: string) => `/${path}`, reportError: () => {} },
      lifetime.signal,
    );
    const state = { expressions: {}, bones: {}, motion: "first.vrma" };
    await session.apply(state, "play", lifetime.signal);
    const controller = new AbortController();
    const pending = session.apply({ ...state, motion: "slow.vrma" }, "play", controller.signal);
    const duringLoading = session.readState().motion;
    const latest = session.apply({ ...state, motion: "latest.vrma" }, "play", lifetime.signal);
    // Per-sentence cleanup must not discard an already queued live action.
    controller.abort();
    const seen = [duringLoading];
    const loaded = Promise.all([pending, latest]);
    const failed = await session.apply({ ...state, motion: "broken.vrma" }, "play", lifetime.signal).then(
      () => false,
      () => true,
    );
    const deadline = performance.now() + 10000;
    while (performance.now() < deadline) {
      const active = session.readState().motion;
      if (seen.at(-1) !== active) seen.push(active);
      if (active === "latest.vrma") break;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    await loaded;
    session.dispose();
    return { duringLoading, failed, seen };
  });
  expect(result).toEqual({
    duringLoading: "first.vrma",
    failed: true,
    seen: ["first.vrma", "slow.vrma", "latest.vrma"],
  });
  await page.waitForTimeout(550);
});
