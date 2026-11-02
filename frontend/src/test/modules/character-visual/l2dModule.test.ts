import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { create } from "../../../modules/character-visual/adapters/l2d/module";
import type { AvatarSession } from "../../../modules/character-visual/contracts";
import type { L2DState, L2DControls } from "../../../modules/character-visual/adapters/l2d/state";
import { neutralState } from "../../../modules/character-visual/adapters/l2d/state";
import type { CubismSdk, SdkModel } from "../../../modules/character-visual/adapters/l2d/sdk";

const loadSdk = vi.hoisted(() => vi.fn());
vi.mock("../../../modules/character-visual/adapters/l2d/sdk", () => ({ loadSdk }));

const ids = ["ParamAngleX", "ParamMouthOpenY", "ParamEyeLOpen", "ParamMouthForm"];
const defaults = [0, 0, 1, 0.5];
let values: number[];
let frame: FrameRequestCallback;
let host: HTMLDivElement;
let definition: Record<string, unknown>;
const sessions: AvatarSession<L2DState, L2DControls>[] = [];
const json = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).buffer as ArrayBuffer;
const fetchResource = vi.fn();
const bitmap = { close: vi.fn() };
const loseContext = vi.fn();
const gl = {
  createTexture: vi.fn(() => ({})),
  deleteTexture: vi.fn(),
  bindTexture: vi.fn(),
  texParameteri: vi.fn(),
  texImage2D: vi.fn(),
  viewport: vi.fn(),
  clearColor: vi.fn(),
  clear: vi.fn(),
  getExtension: vi.fn(() => ({ loseContext })),
};
const matrix = { scale: vi.fn(), multiplyByMatrix: vi.fn() };
const renderer = {
  startUp: vi.fn(),
  setIsPremultipliedAlpha: vi.fn(),
  bindTexture: vi.fn(),
  setMvpMatrix: vi.fn(),
  setRenderState: vi.fn(),
  drawModel: vi.fn(),
};
const modelData: SdkModel = {
  getParameterCount: () => ids.length,
  getParameterId: (index) => ({ getString: () => ({ s: ids[index] }) }),
  getParameterMinimumValue: (index) => (index === 0 ? -30 : 0),
  getParameterMaximumValue: (index) => (index === 0 ? 30 : 1),
  getParameterDefaultValue: (index) => defaults[index],
  getParameterValueByIndex: (index) => values[index],
  setParameterValueByIndex: (index, value) => {
    values[index] = value;
  },
  getPartCount: () => 1,
  getPartOpacityByIndex: () => 1,
  setPartOpacityByIndex: vi.fn(),
  getCanvasWidth: () => 2,
  getCanvasHeight: () => 3,
  update: vi.fn(),
};
const motion = { release: vi.fn() };
const model = {
  loadModel: vi.fn(),
  loadMotion: vi.fn(() => motion),
  loadPhysics: vi.fn(),
  loadPose: vi.fn(),
  getModel: vi.fn(() => modelData),
  getModelMatrix: () => matrix,
  createRenderer: vi.fn(),
  getRenderer: () => renderer,
  resetMotion: vi.fn(),
  play: vi.fn(),
  motionFinished: vi.fn(() => true),
  animate: vi.fn(),
  physics: vi.fn(),
  pose: vi.fn(),
  release: vi.fn(),
};
const sdk: CubismSdk = {
  SDK_VERSION: "5-r.4",
  initialize: vi.fn(),
  createModel: () => model,
  createMatrix: () => matrix,
  releaseContext: vi.fn(),
};
const reportError = vi.fn();
const mount = () => ({ element: host, modelUrl: "/entry", assetUrl: (path: string) => `/${path}`, reportError });
async function start(signal = new AbortController().signal) {
  const session = await create(mount(), signal);
  sessions.push(session);
  return session;
}
const response = (value: unknown) => ({ ok: true, arrayBuffer: async () => json(value) });

beforeEach(() => {
  vi.resetAllMocks();
  vi.spyOn(performance, "now").mockReturnValue(0);
  host = document.createElement("div");
  document.body.append(host);
  values = [...defaults];
  definition = {
    FileReferences: {
      Moc: "model.moc3",
      Textures: ["texture.png"],
      Physics: "physics.json",
      Pose: "pose.json",
      Expressions: [{ File: "add.exp3.json" }, { File: "multiply.exp3.json" }, { File: "overwrite.exp3.json" }],
      Motions: { Idle: [{ File: "wave.motion3.json" }] },
    },
    Groups: [
      { Name: "LipSync", Target: "Parameter", Ids: [ids[1]] },
      { Name: "EyeBlink", Target: "Parameter", Ids: [ids[2]] },
    ],
  };
  fetchResource.mockImplementation(async (url: string) => {
    if (url === "/entry") return response(definition);
    if (url.endsWith("exp3.json"))
      return response({
        Parameters: [
          {
            Id: ids[0],
            Value: url.startsWith("/add") ? 2 : url.startsWith("/multiply") ? 0.5 : 12,
            Blend: url.startsWith("/add") ? "Add" : url.startsWith("/multiply") ? "Multiply" : "Overwrite",
          },
        ],
      });
    return response({ Curves: [{ Target: "Parameter", Id: ids[2] }] });
  });
  loadSdk.mockResolvedValue(sdk);
  model.getModel.mockReturnValue(modelData);
  model.loadMotion.mockReturnValue(motion);
  model.motionFinished.mockReturnValue(true);
  gl.createTexture.mockReturnValue({});
  gl.getExtension.mockReturnValue({ loseContext });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => gl as unknown as WebGLRenderingContext);
  vi.stubGlobal("fetch", fetchResource);
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn(async () => bitmap),
  );
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((callback: FrameRequestCallback) => {
      frame = callback;
      return 1;
    }),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});
afterEach(() => {
  sessions.splice(0).forEach((session) => session.dispose());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Live2D model lifecycle without licensed SDK assets", () => {
  it("adds speech head motion to the base pose without baking it into states or transitions", async () => {
    definition.Groups = [];
    const session = await start();
    const state = { ...neutralState(), parameters: { ParamAngleX: 10 } };
    await session.apply(state, "restore", new AbortController().signal);
    expect(session.capabilities.mouth).toBe(false);
    session.setSpeechLevel!(0.8);
    frame(100);
    const angles: number[] = [];
    for (let i = 1; i <= 120; i++) {
      frame(100 + i * (1000 / 60));
      angles.push(values[0]);
    }
    expect(angles.some((angle) => Math.abs(angle - 10) > 0.2)).toBe(true);
    expect(angles.every((angle) => Math.abs(angle - 10) < 2.2)).toBe(true);
    expect(session.readState()).toEqual(state);
    session.setSpeechLevel!(0);
    for (let i = 121; i <= 300; i++) frame(100 + i * (1000 / 60));
    expect(values[0]).toBe(10);
    await session.apply(
      { ...neutralState(), parameters: { ParamAngleX: 30 } },
      "restore",
      new AbortController().signal,
    );
    session.setSpeechLevel!(1);
    for (let i = 301; i <= 420; i++) {
      frame(100 + i * (1000 / 60));
      expect(values[0]).toBeLessThanOrEqual(30);
    }
  });

  it("keeps speech head motion out of edit mode and reduced-motion playback", async () => {
    const preference = { matches: false };
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => preference),
    );
    const session = await start();
    const state = { ...neutralState(), parameters: { ParamAngleX: 12 } };
    await session.apply(state, "edit", new AbortController().signal);
    session.setSpeechLevel!(1);
    frame(100);
    frame(200);
    expect(values[0]).toBe(12);
    preference.matches = true;
    await session.apply(state, "restore", new AbortController().signal);
    for (let i = 0; i < 30; i++) frame(250 + i * 50);
    expect(values[0]).toBe(12);
  });

  it("yields head parameters to explicit motions until they finish", async () => {
    const originalFetch = fetchResource.getMockImplementation()!;
    fetchResource.mockImplementation((url: string) =>
      url.endsWith("motion3.json") ? response({ Curves: [{ Target: "Parameter", Id: ids[0] }] }) : originalFetch(url),
    );
    model.motionFinished.mockReturnValue(false);
    const session = await start();
    await session.apply({ ...neutralState(), motion: "wave.motion3.json" }, "play", new AbortController().signal);
    session.setSpeechLevel!(1);
    frame(100);
    for (let i = 1; i <= 30; i++) frame(100 + i * 50);
    expect(values[0]).toBe(0);
    model.motionFinished.mockReturnValue(true);
    frame(1650);
    expect(Math.abs(values[0])).toBeGreaterThan(0);
  });

  it("skips missing head parameters without inventing bindings", async () => {
    definition.FileReferences = { Moc: "model.moc3", Textures: [] };
    vi.spyOn(modelData, "getParameterId").mockImplementation((index) => ({
      getString: () => ({ s: index === 0 ? "CustomParameter" : ids[index] }),
    }));
    const session = await start();
    session.setSpeechLevel!(1);
    frame(100);
    frame(200);
    expect(values[0]).toBe(0);
    expect(reportError).not.toHaveBeenCalled();
  });

  it("loads declared resources, reports real bindings, resizes and draws", async () => {
    const session = await start();
    expect(session.capabilities).toEqual({ mouth: true, blink: true, motion: true, sampling: "none" });
    expect(session.controls.parameters).toHaveLength(4);
    expect(model.loadPhysics).toHaveBeenCalled();
    expect(model.loadPose).toHaveBeenCalled();
    expect(renderer.bindTexture).toHaveBeenCalledWith(0, expect.any(Object));
    expect(bitmap.close).toHaveBeenCalled();
    session.resize(600, 700);
    frame(100);
    expect(renderer.drawModel).toHaveBeenCalled();
    expect(matrix.multiplyByMatrix).toHaveBeenCalledWith(matrix);
    session.resize(0, 0);
    expect(host.querySelector("canvas")!.width).toBe(1);
    session.resize(100000, 100000);
    expect(host.querySelector("canvas")!.width).toBe(4096);
  });

  it("preserves model proportions when framed rendering exceeds the canvas limit", async () => {
    const session = await start();
    session.resize(3000, 6000);
    const canvas = host.querySelector("canvas")!;
    expect([canvas.width, canvas.height]).toEqual([2048, 4096]);
    frame(100);
    const [x, y] = matrix.scale.mock.calls.at(-1)!;
    expect(x).toBeCloseTo(1.425);
    expect(y).toBeCloseTo(0.7125);
  });

  it("keeps edit state independent of mouth, blink, motion and physics", async () => {
    const session = await start();
    const state = {
      parameters: { ParamAngleX: 7, ParamEyeLOpen: 0.25 },
      expressions: ["add.exp3.json", "multiply.exp3.json", "overwrite.exp3.json"],
      motion: "wave.motion3.json",
    };
    await session.apply(state, "edit", new AbortController().signal);
    session.setMouthOpen(1);
    frame(5000);
    expect(values).toEqual([12, 0, 0.25, 0.5]);
    expect(model.animate).not.toHaveBeenCalled();
    expect(model.physics).not.toHaveBeenCalled();
    expect(model.pose).toHaveBeenLastCalledWith(0);
    expect(model.loadMotion).not.toHaveBeenCalled();
    const copy = session.readState();
    copy.parameters.ParamAngleX = 30;
    expect(session.readState()).toEqual(state);
  });

  it("plays once, reuses a loaded motion and never replays on restore", async () => {
    const session = await start();
    const state = { ...neutralState(), motion: "wave.motion3.json" };
    await session.apply(state, "restore", new AbortController().signal);
    expect(model.play).not.toHaveBeenCalled();
    await session.apply(state, "play", new AbortController().signal);
    await session.apply(state, "play", new AbortController().signal);
    expect(model.loadMotion).toHaveBeenCalledOnce();
    expect(model.play).toHaveBeenCalledTimes(2);
    await session.apply(state, "restore", new AbortController().signal);
    expect(model.play).toHaveBeenCalledTimes(2);
  });

  it("smoothly switches saved poses in one canvas while readState keeps the target", async () => {
    const session = await start();
    const canvas = host.querySelector("canvas");
    await session.apply(neutralState(), "restore", new AbortController().signal);
    frame(0);
    vi.mocked(performance.now).mockReturnValue(100);
    const next = { ...neutralState(), parameters: { ParamAngleX: 20 } };
    await session.apply(next, "play", new AbortController().signal);
    expect(session.readState()).toEqual(next);
    frame(100);
    expect(values[0]).toBe(0);
    frame(175);
    expect(values[0]).toBeCloseTo(3.125);
    frame(250);
    expect(values[0]).toBe(10);
    frame(400);
    expect(values[0]).toBe(20);
    expect(host.querySelector("canvas")).toBe(canvas);
    expect(model.loadModel).toHaveBeenCalledOnce();
    expect(model.release).not.toHaveBeenCalled();
  });

  it("blends expression operations and clears removed parameters without residue", async () => {
    const session = await start();
    await session.apply(
      { ...neutralState(), parameters: { ParamAngleX: 10 }, expressions: ["add.exp3.json", "multiply.exp3.json"] },
      "restore",
      new AbortController().signal,
    );
    frame(0);
    expect(values[0]).toBe(6);
    await session.apply(
      { ...neutralState(), expressions: ["overwrite.exp3.json"] },
      "play",
      new AbortController().signal,
    );
    frame(150);
    expect(values[0]).toBe(9);
    frame(300);
    expect(values[0]).toBe(12);
    vi.mocked(performance.now).mockReturnValue(300);
    await session.apply(neutralState(), "play", new AbortController().signal);
    frame(450);
    expect(values[0]).toBe(6);
    frame(600);
    expect(values).toEqual(defaults);
  });

  it("retargets rapid state changes without jumping to the interrupted destination", async () => {
    const session = await start();
    await session.apply(neutralState(), "restore", new AbortController().signal);
    frame(0);
    await session.apply({ ...neutralState(), parameters: { ParamAngleX: 20 } }, "play", new AbortController().signal);
    frame(150);
    expect(values[0]).toBe(10);
    vi.mocked(performance.now).mockReturnValue(150);
    await session.apply({ ...neutralState(), parameters: { ParamAngleX: -20 } }, "play", new AbortController().signal);
    frame(150);
    expect(values[0]).toBe(10);
    frame(300);
    expect(values[0]).toBe(-5);
    frame(450);
    expect(values[0]).toBe(-20);
  });

  it.each(["restore", "edit"] as const)("applies %s immediately during a transition", async (mode) => {
    const session = await start();
    await session.apply(neutralState(), "restore", new AbortController().signal);
    frame(0);
    await session.apply({ ...neutralState(), parameters: { ParamAngleX: 20 } }, "play", new AbortController().signal);
    frame(150);
    await session.apply({ ...neutralState(), parameters: { ParamAngleX: -10 } }, mode, new AbortController().signal);
    frame(150);
    expect(values[0]).toBe(-10);
    expect(model.play).not.toHaveBeenCalled();
  });

  it("preserves blink and part fading, and never bakes voice or physics into the transition", async () => {
    const session = await start();
    await session.apply(neutralState(), "restore", new AbortController().signal);
    model.physics.mockImplementation(() => modelData.setParameterValueByIndex(0, 25));
    session.setMouthOpen(1);
    frame(3000);
    expect(values[0]).toBe(25);
    expect(values[1]).toBe(1);
    model.physics.mockImplementation(() => {});
    modelData.setPartOpacityByIndex = vi.fn();
    vi.mocked(performance.now).mockReturnValue(3000);
    await session.apply({ ...neutralState(), parameters: { ParamAngleX: 20 } }, "play", new AbortController().signal);
    expect(modelData.setPartOpacityByIndex).not.toHaveBeenCalled();
    session.setMouthOpen(0);
    frame(3000);
    expect(values[0]).toBe(0);
    expect(values[1]).toBe(0);
    frame(3100);
    expect(values[2]).toBe(0);
    session.setMouthOpen(0.8);
    frame(3150);
    expect(values[0]).toBe(10);
    expect(values[1]).toBe(0.8);
  });

  it("respects reduced motion for pose transitions", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: true })),
    );
    const session = await start();
    await session.apply(neutralState(), "restore", new AbortController().signal);
    frame(0);
    await session.apply({ ...neutralState(), parameters: { ParamAngleX: 20 } }, "play", new AbortController().signal);
    frame(0);
    expect(values[0]).toBe(20);
  });

  it("mixes blink with base eye openness and mouth with smile independently", async () => {
    const session = await start();
    await session.apply(
      { ...neutralState(), parameters: { ParamEyeLOpen: 0.5 } },
      "restore",
      new AbortController().signal,
    );
    session.setMouthOpen(2);
    frame(3000);
    frame(3100);
    expect(values).toEqual([0, 1, 0, 0.5]);
    frame(3150);
    expect(values[2]).toBe(0);
    frame(3300);
    expect(values[2]).toBe(0.5);
    session.setMouthOpen(NaN);
    frame(3400);
    expect(values[1]).toBe(0);
    session.setMouthOpen(-1);
    frame(3500);
    expect(values[1]).toBe(0);
    expect(session.readState().parameters).toEqual({ ParamEyeLOpen: 0.5 });
  });

  it("does not overlay blink on eyes controlled by an active motion", async () => {
    model.motionFinished.mockReturnValue(false);
    const session = await start();
    await session.apply({ ...neutralState(), motion: "wave.motion3.json" }, "play", new AbortController().signal);
    frame(3000);
    frame(3100);
    expect(values[2]).toBe(1);
    model.motionFinished.mockReturnValue(true);
    frame(3150);
    expect(values[2]).toBe(0);
  });

  it("rejects invalid state and honours a pre-cancelled apply", async () => {
    const session = await start();
    await expect(
      session.apply({ ...neutralState(), parameters: { unknown: 1 } }, "edit", new AbortController().signal),
    ).rejects.toThrow("out-of-range");
    const abort = new AbortController();
    abort.abort();
    await expect(session.apply(neutralState(), "play", abort.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(session.readState()).toEqual(neutralState());
  });

  it("does not let a late motion response overwrite a newer state", async () => {
    const session = await start();
    let resolve!: (buffer: ArrayBuffer) => void;
    fetchResource.mockResolvedValue({
      ok: true,
      arrayBuffer: () =>
        new Promise<ArrayBuffer>((done) => {
          resolve = done;
        }),
    });
    const late = session.apply(
      { ...neutralState(), motion: "wave.motion3.json" },
      "play",
      new AbortController().signal,
    );
    await vi.waitFor(() => expect(resolve).toBeDefined());
    const newer = { ...neutralState(), parameters: { ParamAngleX: 10 } };
    await session.apply(newer, "restore", new AbortController().signal);
    resolve(json({}));
    await late;
    expect(session.readState()).toEqual(newer);
    expect(model.play).not.toHaveBeenCalled();
  });

  it("cancels in-flight motion application without mutating state", async () => {
    const session = await start();
    let resolve!: (buffer: ArrayBuffer) => void;
    fetchResource.mockResolvedValue({
      ok: true,
      arrayBuffer: () =>
        new Promise<ArrayBuffer>((done) => {
          resolve = done;
        }),
    });
    const abort = new AbortController();
    const applying = session.apply({ ...neutralState(), motion: "wave.motion3.json" }, "play", abort.signal);
    await vi.waitFor(() => expect(resolve).toBeDefined());
    abort.abort();
    resolve(json({}));
    await expect(applying).rejects.toMatchObject({ name: "AbortError" });
    expect(session.readState()).toEqual(neutralState());
  });

  it("releases motion, texture, canvas and GPU once even with repeated disposal", async () => {
    const session = await start();
    await session.apply({ ...neutralState(), motion: "wave.motion3.json" }, "play", new AbortController().signal);
    session.dispose();
    session.dispose();
    frame(0);
    session.resize(10, 10);
    session.setMouthOpen(1);
    expect(model.release).toHaveBeenCalledOnce();
    expect(motion.release).toHaveBeenCalledOnce();
    expect(gl.deleteTexture).toHaveBeenCalledOnce();
    expect(loseContext).toHaveBeenCalledOnce();
    expect(sdk.releaseContext).toHaveBeenCalledWith(gl, true);
    expect(host.querySelector("canvas")).toBeNull();
    expect(renderer.drawModel).not.toHaveBeenCalled();
  });

  it("keeps the shared shader manager alive until the final instance is disposed", async () => {
    const first = await start(),
      second = await start();
    first.dispose();
    expect(sdk.releaseContext).toHaveBeenLastCalledWith(gl, false);
    second.dispose();
    expect(sdk.releaseContext).toHaveBeenLastCalledWith(gl, true);
  });

  it("cleans up and reports context loss", async () => {
    await start();
    host.querySelector("canvas")!.dispatchEvent(new Event("webglcontextlost", { cancelable: true }));
    expect(reportError).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining("context lost") }),
    );
    expect(host.querySelector("canvas")).toBeNull();
  });

  it.each([new Error("draw failed"), "draw failed"])("cleans up and reports frame errors", async (error) => {
    await start();
    renderer.drawModel.mockImplementationOnce(() => {
      throw error;
    });
    frame(100);
    expect(reportError).toHaveBeenCalledWith(expect.objectContaining({ message: "draw failed" }));
    expect(host.querySelector("canvas")).toBeNull();
  });

  it("rejects failed resource requests and releases the partial instance", async () => {
    fetchResource.mockResolvedValue({ ok: false, status: 403 });
    await expect(start()).rejects.toThrow("403");
    expect(model.release).toHaveBeenCalled();
  });

  it.each([
    { Id: "unknown", Value: 1 },
    { Id: ids[0], Value: null },
    { Id: ids[0], Value: 1, Blend: "invalid" },
  ])("rejects invalid expression parameters: %j", async (parameter) => {
    fetchResource.mockImplementation(async (url: string) =>
      response(url === "/entry" ? definition : { Parameters: [parameter] }),
    );
    await expect(start()).rejects.toThrow("Invalid expression");
    expect(model.release).toHaveBeenCalled();
  });

  it("closes decoded images even when texture allocation fails", async () => {
    gl.createTexture.mockReturnValueOnce(null as unknown as object);
    await expect(start()).rejects.toThrow("allocate");
    expect(bitmap.close).toHaveBeenCalled();
  });

  it("supports models without eye/mouth bindings or optional resources", async () => {
    definition = { FileReferences: { Moc: "model.moc3", Textures: [] } };
    const session = await start();
    expect(session.capabilities).toEqual({ mouth: false, blink: false, motion: false, sampling: "none" });
    frame(0);
    expect(renderer.drawModel).toHaveBeenCalled();
  });

  it("rejects missing WebGL, invalid moc data and missing motion instances", async () => {
    vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValueOnce(null);
    await expect(start()).rejects.toThrow("WebGL");
    model.getModel.mockReturnValueOnce(null as unknown as SdkModel);
    await expect(start()).rejects.toThrow("moc3");
    const session = await start();
    model.loadMotion.mockReturnValueOnce(null as unknown as typeof motion);
    await expect(
      session.apply({ ...neutralState(), motion: "wave.motion3.json" }, "play", new AbortController().signal),
    ).rejects.toThrow("Invalid Live2D motion");
  });

  it("surfaces an unavailable SDK without allocating a canvas", async () => {
    loadSdk.mockRejectedValue(new Error("SDK unavailable"));
    await expect(start()).rejects.toThrow("SDK unavailable");
    expect(host.querySelector("canvas")).toBeNull();
  });
});
