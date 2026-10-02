import type { ApplyMode, AvatarMount, AvatarSession } from "../../contracts";
import { loadSdk, type SdkMotion } from "./sdk";
import { ParameterTransition } from "../../parameterTransition";
import { TalkingHeadMotion } from "../../talkingHeadMotion";
import { neutralState, packagePath, parseState, validateControls, type L2DControls, type L2DState } from "./state";
export { Editor } from "./Editor";

type Expression = { Parameters: Array<{ Id: string; Value: number; Blend?: string }> };
let activeModels = 0;

export async function create(mount: AvatarMount, signal: AbortSignal): Promise<AvatarSession<L2DState, L2DControls>> {
  const sdk = await loadSdk(signal, mount.runtimeAssetUrl);
  sdk.initialize();
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "display:block;width:100%;height:100%";
  const gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true });
  if (!gl) throw new Error("Live2D requires WebGL");
  const model = sdk.createModel();
  ++activeModels;
  const textures: WebGLTexture[] = [];
  const motions = new Map<string, SdkMotion>();
  const expressions = new Map<string, Expression>();
  let frame = 0,
    disposed = false,
    generation = 0;
  let current = neutralState();
  const transition = new ParameterTransition();
  const talkingHead = new TalkingHeadMotion();
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let hasAppliedState = false;
  let mode: ApplyMode = "restore";
  let mouth = 0,
    lastTime = 0,
    blinkStart = -1,
    nextBlink = 0;
  let motionParameters = new Set<string>();
  const requests = new AbortController();
  const cancel = () => requests.abort();
  signal.addEventListener("abort", cancel, { once: true });
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    ++generation;
    requests.abort();
    signal.removeEventListener("abort", cancel);
    cancelAnimationFrame(frame);
    canvas.removeEventListener("webglcontextlost", contextLost);
    model.release();
    for (const motion of motions.values()) motion.release();
    motions.clear();
    for (const texture of textures) gl.deleteTexture(texture);
    sdk.releaseContext(gl, --activeModels === 0);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    canvas.remove();
  };
  const contextLost = (event: Event) => {
    event.preventDefault();
    if (!disposed) {
      dispose();
      mount.reportError(new Error("Live2D WebGL context lost; reload model"));
    }
  };
  const bytes = async (url: string, abort = requests.signal) => {
    const response = await fetch(url, { signal: abort });
    if (!response.ok) throw new Error(`Live2D resource request failed: ${response.status}`);
    const result = await response.arrayBuffer();
    abort.throwIfAborted();
    if (disposed) throw new Error("Live2D instance disposed");
    return result;
  };
  const assetBytes = (path: string, abort?: AbortSignal) => bytes(mount.assetUrl(packagePath(path)), abort);
  try {
    const entry = await bytes(mount.modelUrl);
    const definition = JSON.parse(new TextDecoder().decode(entry)) as {
      FileReferences: {
        Moc: string;
        Textures: string[];
        Physics?: string;
        Pose?: string;
        Expressions?: Array<{ File: string }>;
        Motions?: Record<string, Array<{ File: string }>>;
      };
      Groups?: Array<{ Name: string; Target: string; Ids: string[] }>;
    };
    const refs = definition.FileReferences;
    model.loadModel(await assetBytes(refs.Moc), true);
    const sdkModel = model.getModel();
    if (!sdkModel) throw new Error("Invalid or incompatible Live2D moc3 model");
    const controls: L2DControls = {
      parameters: Array.from({ length: sdkModel.getParameterCount() }, (_, index) => ({
        id: sdkModel.getParameterId(index).getString().s,
        min: sdkModel.getParameterMinimumValue(index),
        max: sdkModel.getParameterMaximumValue(index),
        default: sdkModel.getParameterDefaultValue(index),
      })),
      expressions: (refs.Expressions ?? []).map((item) => packagePath(item.File)),
      motions: Object.values(refs.Motions ?? {})
        .flat()
        .map((item) => packagePath(item.File)),
    };
    const indexes = new Map(controls.parameters.map((parameter, index) => [parameter.id, index]));
    const headParameters = (["ParamAngleX", "ParamAngleY", "ParamAngleZ"] as const).flatMap((id, axis) => {
      const index = indexes.get(id);
      return index === undefined ? [] : [{ id, axis, index, parameter: controls.parameters[index] }];
    });
    const group = (name: string) =>
      (definition.Groups ?? [])
        .filter((item) => item.Target === "Parameter" && item.Name === name)
        .flatMap((item) => item.Ids)
        .filter((id) => indexes.has(id));
    const lips = group("LipSync"),
      eyes = group("EyeBlink");
    const parts = Array.from({ length: sdkModel.getPartCount() }, (_, i) => sdkModel.getPartOpacityByIndex(i));
    if (refs.Physics) {
      const data = await assetBytes(refs.Physics);
      model.loadPhysics(data, data.byteLength);
    }
    if (refs.Pose) {
      const data = await assetBytes(refs.Pose);
      model.loadPose(data, data.byteLength);
    }
    for (const path of controls.expressions) {
      const data = JSON.parse(new TextDecoder().decode(await assetBytes(path))) as Expression;
      for (const parameter of data.Parameters ?? []) {
        if (
          !indexes.has(parameter.Id) ||
          !Number.isFinite(parameter.Value) ||
          !["Add", "Multiply", "Overwrite"].includes(parameter.Blend ?? "Add")
        )
          throw new Error(`Invalid expression parameter: ${parameter.Id}`);
      }
      expressions.set(path, data);
    }
    model.createRenderer();
    const renderer = model.getRenderer();
    renderer.startUp(gl);
    renderer.setIsPremultipliedAlpha(true);
    for (let index = 0; index < refs.Textures.length; index++) {
      const image = await createImageBitmap(new Blob([await assetBytes(refs.Textures[index])]), {
        premultiplyAlpha: "premultiply",
      });
      try {
        requests.signal.throwIfAborted();
        const texture = gl.createTexture();
        if (!texture) throw new Error("Could not allocate Live2D texture");
        textures.push(texture);
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
        renderer.bindTexture(index, texture);
      } finally {
        image.close();
      }
    }
    signal.throwIfAborted();
    mount.element.append(canvas);
    canvas.addEventListener("webglcontextlost", contextLost);
    const reset = (resetParts = true) => {
      controls.parameters.forEach((parameter, index) => sdkModel.setParameterValueByIndex(index, parameter.default));
      if (resetParts) parts.forEach((opacity, index) => sdkModel.setPartOpacityByIndex(index, opacity));
    };
    const update = (time: number) => {
      if (disposed) return;
      try {
        const dt = Math.min(0.05, Math.max(0, (time - (lastTime || time)) / 1000));
        lastTime = time;
        reset(false);
        if (mode !== "edit") {
          model.animate(dt);
          if (model.motionFinished()) motionParameters.clear();
        }
        for (const [id, value] of Object.entries(current.parameters))
          sdkModel.setParameterValueByIndex(indexes.get(id)!, value);
        for (const path of current.expressions)
          for (const parameter of expressions.get(path)!.Parameters ?? []) {
            const index = indexes.get(parameter.Id)!;
            const base = sdkModel.getParameterValueByIndex(index);
            sdkModel.setParameterValueByIndex(
              index,
              parameter.Blend === "Overwrite"
                ? parameter.Value
                : parameter.Blend === "Multiply"
                  ? base * parameter.Value
                  : base + parameter.Value,
            );
          }
        const target = controls.parameters.map((_, index) => sdkModel.getParameterValueByIndex(index));
        transition.sample(target, time).forEach((value, index) => sdkModel.setParameterValueByIndex(index, value));
        const rotation = talkingHead.sample(dt, mode !== "edit" && !reducedMotion?.matches);
        if (mode !== "edit") {
          const angles = [rotation.yaw, rotation.pitch, rotation.roll];
          for (const { id, axis, index, parameter } of headParameters)
            if (!motionParameters.has(id)) {
              const scale = Math.min(1, (parameter.max - parameter.min) / 60);
              const value = sdkModel.getParameterValueByIndex(index) + (angles[axis] * 180 * scale) / Math.PI;
              sdkModel.setParameterValueByIndex(index, Math.max(parameter.min, Math.min(parameter.max, value)));
            }
          if (time >= nextBlink && blinkStart < 0) blinkStart = time;
          if (blinkStart >= 0) {
            const elapsed = time - blinkStart;
            const openness = elapsed < 100 ? 1 - elapsed / 100 : elapsed < 150 ? 0 : Math.min(1, (elapsed - 150) / 150);
            for (const id of eyes)
              if (!motionParameters.has(id)) {
                const index = indexes.get(id)!;
                sdkModel.setParameterValueByIndex(index, sdkModel.getParameterValueByIndex(index) * openness);
              }
            if (elapsed >= 300) {
              blinkStart = -1;
              nextBlink = time + 2500 + Math.random() * 2000;
            }
          }
          for (const id of lips) {
            const index = indexes.get(id)!;
            const max = controls.parameters[index].max;
            sdkModel.setParameterValueByIndex(index, Math.max(sdkModel.getParameterValueByIndex(index), mouth * max));
          }
          model.physics(dt);
        }
        model.pose(mode === "edit" ? 0 : dt);
        sdkModel.update();
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        const matrix = sdk.createMatrix();
        const aspect = canvas.width / Math.max(1, canvas.height);
        const modelAspect = sdkModel.getCanvasWidth() / sdkModel.getCanvasHeight();
        const fit = Math.min(1, aspect / modelAspect) * 0.95;
        matrix.scale(fit / aspect, fit);
        matrix.multiplyByMatrix(model.getModelMatrix());
        renderer.setMvpMatrix(matrix);
        renderer.setRenderState(null, [0, 0, canvas.width, canvas.height]);
        renderer.drawModel();
        frame = requestAnimationFrame(update);
      } catch (error) {
        dispose();
        mount.reportError(error instanceof Error ? error : new Error(String(error)));
      }
    };
    frame = requestAnimationFrame(update);
    return {
      capabilities: {
        mouth: lips.length > 0,
        blink: eyes.length > 0,
        motion: controls.motions.length > 0,
        sampling: "none",
      },
      controls,
      async apply(value, nextMode, abort) {
        abort.throwIfAborted();
        const request = ++generation;
        const next = parseState(value);
        validateControls(next, controls);
        let motion: SdkMotion | undefined;
        let drivenParameters = new Set<string>();
        if (nextMode === "play" && next.motion) {
          const data = await assetBytes(next.motion, abort);
          const metadata = JSON.parse(new TextDecoder().decode(data)) as {
            Curves?: Array<{ Target: string; Id: string }>;
          };
          drivenParameters = new Set(
            (metadata.Curves ?? []).filter((curve) => curve.Target === "Parameter").map((curve) => curve.Id),
          );
          abort.throwIfAborted();
          if (request !== generation || disposed) return;
          motion = motions.get(next.motion);
          if (!motion) {
            const loadedMotion = model.loadMotion(data, data.byteLength, next.motion);
            if (!loadedMotion) throw new Error("Invalid Live2D motion");
            motion = loadedMotion;
            motions.set(next.motion, motion);
          }
        }
        abort.throwIfAborted();
        if (request !== generation || disposed) return;
        const now = performance.now();
        const animate = nextMode === "play" && hasAppliedState;
        transition.start(animate && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches, now);
        model.resetMotion();
        // Do not reset part opacity while changing expression: pose owns its fade.
        if (!animate) reset();
        current = structuredClone(next);
        mode = nextMode;
        motionParameters = drivenParameters;
        if (mode === "edit") {
          mouth = 0;
          talkingHead.reset();
        }
        if (!animate) {
          blinkStart = -1;
          nextBlink = now + 3000;
        }
        hasAppliedState = true;
        if (motion) model.play(motion);
      },
      readState: () => structuredClone(current),
      setMouthOpen(value) {
        if (!disposed) mouth = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
      },
      setSpeechLevel(value) {
        if (!disposed) talkingHead.setLevel(value);
      },
      resize(width, height) {
        if (disposed) return;
        const ratio = Math.min(2, window.devicePixelRatio || 1);
        canvas.width = Math.max(1, Math.min(4096, Math.round(width * ratio)));
        canvas.height = Math.max(1, Math.min(4096, Math.round(height * ratio)));
      },
      dispose,
    };
  } catch (error) {
    dispose();
    throw error;
  }
}
