import { Engine } from "@babylonjs/core/Engines/engine";
import { Color4 } from "@babylonjs/core/Maths/math.color";
import { LoadAssetContainerAsync } from "@babylonjs/core/Loading/sceneLoader";
import { Mesh } from "@babylonjs/core/Meshes/mesh";
import { Scene } from "@babylonjs/core/scene";
import { MmdStandardMaterialBuilder } from "babylon-mmd/esm/Loader/mmdStandardMaterialBuilder";
import { PmxReader } from "babylon-mmd/esm/Loader/Parser/pmxReader";
import { RegisterPmxLoader } from "babylon-mmd/esm/Loader/pmxLoader.pure";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import { MmdStandardMaterialProxy } from "babylon-mmd/esm/Runtime/mmdStandardMaterialProxy";

import type { ApplyMode, AvatarMount, AvatarSession } from "../../contracts";
import { ParameterTransition } from "../../parameterTransition";
import { TalkingHeadMotion } from "../../talkingHeadMotion";
import { avatarRenderSize } from "../../renderSize";
import { BreathingMotion, createBreathingPose } from "./breathing";
import { createHeadPose } from "./headPose";
import { createView } from "./view";
import { loadMotion, MmdMotionPlayer } from "./motion";
import {
  blinkClosure,
  detectBindings,
  neutralState,
  parseState,
  validateControls,
  type MmdControls,
  type MmdState,
} from "./state";
export { Editor } from "./Editor";

function packagePath(raw: string): string {
  const path = raw.replaceAll("\\", "/");
  if (
    !path ||
    path.startsWith("/") ||
    /[:?#%\x00-\x1f]/.test(path) ||
    path.split("/").some((part) => !part || part === "." || part === "..")
  )
    throw new Error(`Unsafe PMX texture path: ${raw}`);
  return path;
}

function textureType(path: string): string {
  const extension = path.slice(path.lastIndexOf(".")).toLowerCase();
  return (
    { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".bmp": "image/bmp", ".tga": "image/x-tga" }[
      extension
    ] ?? "application/octet-stream"
  );
}

function bundledFile(path: string, bytes: ArrayBuffer): File {
  const file = new File([bytes], path.split("/").at(-1)!, { type: textureType(path) });
  Object.defineProperty(file, "webkitRelativePath", { value: path });
  return file;
}

export async function create(mount: AvatarMount, signal: AbortSignal): Promise<AvatarSession<MmdState, MmdControls>> {
  RegisterPmxLoader();
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "display:block;width:100%;height:100%";
  mount.element.append(canvas);
  // The desktop chat window is created with `transparent(true)`: layered
  // WebView2 windows only composite WebGL content correctly when the drawing
  // buffer is premultiplied. Straight alpha renders invisibly there.
  const engine = new Engine(canvas, true, { alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: true });
  const scene = new Scene(engine);
  // The host owns window dragging; the editor controls the camera via state.
  // Babylon's default pointerdown cancellation suppresses the host's mousedown.
  scene.detachControl();
  scene.clearColor = new Color4(0, 0, 0, 0);
  let runtime: MmdRuntime | undefined;
  let disposed = false;
  const requests = new AbortController();
  const cancel = () => requests.abort();
  signal.addEventListener("abort", cancel, { once: true });
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    requests.abort();
    signal.removeEventListener("abort", cancel);
    engine.stopRenderLoop();
    runtime?.dispose(scene);
    scene.dispose();
    engine.dispose();
    canvas.remove();
  };
  const bytes = async (url: string) => {
    const response = await fetch(url, { signal: requests.signal });
    if (!response.ok) throw new Error(`PMX resource request failed: ${response.status}`);
    const result = await response.arrayBuffer();
    requests.signal.throwIfAborted();
    return result;
  };
  try {
    const data = await bytes(mount.modelUrl);
    const parsed = await PmxReader.ParseAsync(data);
    requests.signal.throwIfAborted();
    const view = createView(scene, parsed);
    const texturePaths = [...new Set(parsed.textures.filter(Boolean).map(packagePath))];
    const references = await Promise.all(
      texturePaths.map(async (path) => bundledFile(path, await bytes(mount.assetUrl(path)))),
    );
    requests.signal.throwIfAborted();
    const modelName =
      new URL(mount.modelUrl, location.href).searchParams.get("model_path")?.split(/[\\/]/).at(-1) ?? "model.pmx";
    const container = await LoadAssetContainerAsync(
      new File([data], modelName, { type: "application/octet-stream" }),
      scene,
      {
        pluginExtension: ".pmx",
        pluginOptions: {
          mmdmodel: { referenceFiles: references, materialBuilder: new MmdStandardMaterialBuilder() },
        },
      },
    );
    requests.signal.throwIfAborted();
    container.addAllToScene();
    const root = container.meshes[0];
    if (!(root instanceof Mesh)) throw new Error("PMX has no root mesh");
    const modelRuntime = (runtime = new MmdRuntime(scene, null));
    const model = modelRuntime.createMmdModel(root, {
      materialProxyConstructor: MmdStandardMaterialProxy,
      buildPhysics: false,
    });
    const controls: MmdControls = {
      morphs: [
        ...new Map(
          model.morph.morphs.map((item) => [
            item.name,
            {
              name: item.name,
              englishName: parsed.morphs.find((entry) => entry.name === item.name)?.englishName ?? "",
              category: parsed.morphs.find((entry) => entry.name === item.name)?.category ?? 4,
            },
          ]),
        ).values(),
      ],
    };
    const bindings = detectBindings(controls.morphs);
    const breathingPose = createBreathingPose(model.runtimeBones, parsed.bones);
    const breathing = new BreathingMotion();
    const headPose = createHeadPose(model.runtimeBones, parsed.bones);
    const talkingHead = new TalkingHeadMotion();
    const motions = new MmdMotionPlayer(model);
    const motionCache = new Map<string, ReturnType<MmdMotionPlayer["bind"]>>();
    let applicationSequence = 0;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let current = neutralState(bindings.mouthMorph, bindings.blinkMorph);
    const capabilities = {
      mouth: Boolean(current.mouthMorph),
      blink: Boolean(current.blinkMorph),
      motion: true,
      sampling: "none" as const,
    };
    let mode: ApplyMode = "restore";
    let mouth = 0;
    let smoothMouth = 0;
    let blinkStart = -1;
    let nextBlink = performance.now() + 3000;
    let hasApplied = false;
    const transition = new ParameterTransition();
    const names = controls.morphs.map((item) => item.name);
    const resize = (width: number, height: number) => {
      if (disposed) return;
      const pixels = avatarRenderSize(width, height, window.devicePixelRatio);
      engine.setSize(pixels.width, pixels.height);
      view.update(current.camera, pixels.width, pixels.height);
    };
    resize(mount.element.clientWidth, mount.element.clientHeight);
    // Transient rotations are inputs to MMD, not edits to its final skinning matrices.
    // Keep them through both solver stages (including after-physics bones), then
    // restore the original local pose so neither snapshots nor later frames drift.
    scene.onBeforeAnimationsObservable.add(() => {
      if (disposed) return;
      try {
        const now = performance.now();
        const dt = Math.min(0.05, engine.getDeltaTime() / 1000);
        model.morph.resetMorphWeights();
        motions.sample(engine.getDeltaTime() / 1000);
        const values = transition.sample(
          names.map((name) => Math.max(current.morphs[name] ?? 0, model.morph.getMorphWeight(name))),
          now,
        );
        names.forEach((name, index) => model.morph.setMorphWeight(name, values[index]));
        if (mode !== "edit") {
          if (now >= nextBlink && blinkStart < 0) blinkStart = now;
          if (blinkStart >= 0) {
            const elapsed = now - blinkStart;
            const closure = blinkClosure(elapsed);
            if (current.blinkMorph && !motions.controlsMorph(current.blinkMorph))
              model.morph.setMorphWeight(
                current.blinkMorph,
                Math.max(model.morph.getMorphWeight(current.blinkMorph), closure),
              );
            if (elapsed >= 300) {
              blinkStart = -1;
              nextBlink = now + 2500 + Math.random() * 2000;
            }
          }
          smoothMouth += (mouth - smoothMouth) * Math.min(1, dt * (mouth > smoothMouth ? 18 : 10));
          if (current.mouthMorph)
            model.morph.setMorphWeight(
              current.mouthMorph,
              Math.max(model.morph.getMorphWeight(current.mouthMorph), smoothMouth),
            );
        }
        const ambientMotion = mode !== "edit" && !reducedMotion?.matches;
        const breath = breathing.sample(dt, ambientMotion && !motions.isAnimating);
        const speech = talkingHead.sample(dt, ambientMotion && !motions.hasPose);
        breathingPose.apply(breath.chestPitch);
        headPose.apply({
          pitch: speech.pitch + breath.head.pitch,
          yaw: speech.yaw + breath.head.yaw,
          roll: speech.roll + breath.head.roll,
        });
        modelRuntime.beforePhysics(engine.getDeltaTime());
      } catch (error) {
        headPose.restore();
        breathingPose.restore();
        dispose();
        mount.reportError(error instanceof Error ? error : new Error(String(error)));
      }
    });
    scene.onBeforeRenderObservable.add(() => {
      if (disposed) return;
      try {
        modelRuntime.afterPhysics();
      } catch (error) {
        headPose.restore();
        breathingPose.restore();
        dispose();
        mount.reportError(error instanceof Error ? error : new Error(String(error)));
      } finally {
        headPose.restore();
        breathingPose.restore();
      }
    });
    engine.runRenderLoop(() => {
      if (!disposed) scene.render();
    });
    return {
      capabilities,
      controls,
      async apply(value, nextMode, abort) {
        const sequence = ++applicationSequence;
        abort.throwIfAborted();
        const next = parseState(value);
        validateControls(next, controls);
        let motion = null;
        if (next.motion) {
          motion = motionCache.get(next.motion) ?? null;
          if (!motion) {
            const animation = await loadMotion(scene, next.motion, await bytes(mount.assetUrl(next.motion)));
            abort.throwIfAborted();
            if (disposed || sequence !== applicationSequence) return;
            motion = motions.bind(animation);
            if (motionCache.size >= 8) motionCache.delete(motionCache.keys().next().value!);
            motionCache.set(next.motion, motion);
          }
        }
        abort.throwIfAborted();
        if (disposed || sequence !== applicationSequence) return;
        const now = performance.now();
        const smooth = nextMode === "play" && hasApplied && !reducedMotion?.matches;
        transition.start(smooth, now);
        motions.set(motion, nextMode === "play" && reducedMotion?.matches ? "restore" : nextMode, smooth);
        current = structuredClone(next);
        view.update(current.camera, engine.getRenderWidth(), engine.getRenderHeight());
        capabilities.mouth = Boolean(current.mouthMorph);
        capabilities.blink = Boolean(current.blinkMorph);
        mode = nextMode;
        if (mode === "edit") {
          smoothMouth = mouth = 0;
          talkingHead.reset();
        }
        hasApplied = true;
      },
      readState: () => structuredClone(current),
      setMouthOpen(value) {
        if (!disposed) mouth = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
      },
      setSpeechLevel(value) {
        if (!disposed) talkingHead.setLevel(value);
      },
      resize,
      dispose,
    };
  } catch (error) {
    dispose();
    throw error;
  }
}
