import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSdkLoader } from "../../../modules/character-visual/adapters/l2d/sdk";

const core = vi.hoisted(() => vi.fn(async (signal: AbortSignal) => signal.throwIfAborted()));
vi.mock("../../../modules/character-visual/adapters/l2d/core", () => ({ loadCore: core }));

const runtime = { SDK_VERSION: "5-r.4", initialize() {}, createModel() {}, createMatrix() {}, releaseContext() {} };
beforeEach(() => vi.clearAllMocks());

describe("optional local Cubism runtime", () => {
  it("loads only the local prepared SDK and shares concurrent imports", async () => {
    const importer = vi.fn(async () => runtime);
    const load = createSdkLoader(importer);
    const signal = new AbortController().signal;
    expect(importer).not.toHaveBeenCalled();
    await expect(Promise.all([load(signal), load(signal)])).resolves.toEqual([runtime, runtime]);
    await expect(load(signal)).resolves.toBe(runtime);
    expect(importer).toHaveBeenCalledOnce();
    expect(importer).toHaveBeenCalledWith(new URL("/live2d/cubism-sdk.js", window.location.href).href);
  });

  it("reports missing resources and permits a later retry", async () => {
    const importer = vi.fn().mockRejectedValueOnce(new Error("missing")).mockResolvedValue(runtime);
    const load = createSdkLoader(importer);
    await expect(load(new AbortController().signal)).rejects.toThrow("prepare:l2d");
    await expect(load(new AbortController().signal)).resolves.toBe(runtime);
  });

  it.each([null, {}, { ...runtime, SDK_VERSION: "5-r.5" }, { ...runtime, initialize: null }])(
    "rejects incompatible runtimes: %j",
    async (value) => {
      const load = createSdkLoader(async () => value);
      await expect(load(new AbortController().signal)).rejects.toMatchObject({
        cause: expect.objectContaining({ message: "Incompatible Cubism SDK runtime; expected 5-r.4" }),
      });
    },
  );

  it("does not import for an already cancelled caller", async () => {
    const importer = vi.fn(async () => runtime);
    const abort = new AbortController();
    abort.abort();
    await expect(createSdkLoader(importer)(abort.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(importer).not.toHaveBeenCalled();
  });

  it("rejects a cancelled caller without poisoning a shared SDK load", async () => {
    let resolve!: (value: unknown) => void;
    const load = createSdkLoader(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const abort = new AbortController();
    const cancelled = load(abort.signal);
    await vi.waitFor(() => expect(resolve).toBeDefined());
    abort.abort();
    resolve(runtime);
    await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    await expect(load(new AbortController().signal)).resolves.toBe(runtime);
  });
});
