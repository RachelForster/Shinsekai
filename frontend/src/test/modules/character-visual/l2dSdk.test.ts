import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSdkLoader } from "../../../modules/character-visual/adapters/l2d/sdk";
import format from "../../../modules/character-visual/adapters/l2d/format";

const core = vi.hoisted(() => vi.fn(async (signal: AbortSignal) => signal.throwIfAborted()));
vi.mock("../../../modules/character-visual/adapters/l2d/core", () => ({ loadCore: core }));

const runtime = { SDK_VERSION: "5-r.4", initialize() {}, createModel() {}, createMatrix() {}, releaseContext() {} };
beforeEach(() => vi.clearAllMocks());

describe("optional local Cubism runtime", () => {
  it("requires a full page reload after installation to clear both global runtime caches", () => {
    expect(format.runtime?.reloadAfterInstall).toBe(true);
  });
  it("loads user-installed runtime assets from the host bridge", async () => {
    const importer = vi.fn(async () => runtime);
    const urls = (file: string) => `http://127.0.0.1:8787/api/avatar/runtime/file?format=l2d&path=${file}&token=test`;
    const signal = new AbortController().signal;
    await expect(createSdkLoader(importer)(signal, urls)).resolves.toBe(runtime);
    expect(core).toHaveBeenCalledWith(signal, urls("live2dcubismcore.min.js"));
    expect(importer).toHaveBeenCalledWith(urls("cubism-sdk.js"));
  });
  it("retains explicitly prepared public runtimes when no host runtime exists", async () => {
    const importer = vi.fn().mockRejectedValueOnce(new Error("missing host runtime")).mockResolvedValue(runtime);
    const urls = (file: string) => `http://localhost/api/avatar/runtime/file?path=${file}`;
    await expect(createSdkLoader(importer)(new AbortController().signal, urls)).resolves.toBe(runtime);
    expect(importer.mock.calls.map(([url]) => url)).toEqual([
      urls("cubism-sdk.js"),
      new URL("/live2d/cubism-sdk.js", window.location.href).href,
    ]);
  });
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
    expect(new URL(importer.mock.calls[1][0]).searchParams.get("sdk_retry")).toBe("1");
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
