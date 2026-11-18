import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName, type VRM } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from "@pixiv/three-vrm-animation";
import type { AvatarMount, AvatarSession, ApplyMode } from "../../contracts";
import { blinkExpressions, emptyState, pairedBlink, parseState, type VrmState, type VrmControls } from "./state";
import { createMotionPlayer } from "./motion";
export { Editor } from "./VrmEditor";

export async function create(mount: AvatarMount, signal: AbortSignal): Promise<AvatarSession<VrmState, VrmControls>> {
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x777777, 2));
  const light = new THREE.DirectionalLight(0xffffff, 2);
  light.position.set(1, 2, 3);
  scene.add(light);
  let vrm: VRM | undefined;
  let disposed = false,
    frame = 0,
    mouth = 0,
    time = 0;
  let state = emptyState(),
    mode: ApplyMode = "restore";
  let motions: ReturnType<typeof createMotionPlayer> | undefined;
  const clips = new Map<string, THREE.AnimationClip>();
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    motions?.dispose();
    if (vrm) {
      VRMUtils.deepDispose(vrm.scene);
    }
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
    signal.removeEventListener("abort", dispose);
  };
  signal.addEventListener("abort", dispose, { once: true });
  const load = async (url: string, abort: AbortSignal) => {
    const response = await fetch(url, { signal: abort });
    if (!response.ok) throw new Error(`Model request failed: ${response.status}`);
    const buffer = await response.arrayBuffer();
    abort.throwIfAborted();
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((path) => {
      if (/^(blob:|data:)/.test(path)) return path;
      return mount.assetUrl(path);
    });
    const loader = new GLTFLoader(manager);
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    const parsed = await loader.parseAsync(buffer, "");
    if (abort.aborted) {
      VRMUtils.deepDispose(parsed.scene);
      abort.throwIfAborted();
    }
    return parsed;
  };
  try {
    const gltf = await load(mount.modelUrl, signal);
    vrm = gltf.userData.vrm as VRM;
    if (!vrm) {
      VRMUtils.deepDispose(gltf.scene);
      throw new Error("This file is not a VRM model");
    }
    if (disposed || signal.aborted) {
      VRMUtils.deepDispose(vrm.scene);
      throw new DOMException("Cancelled", "AbortError");
    }
    VRMUtils.rotateVRM0(vrm);
    scene.add(vrm.scene);
    const expressions = Object.keys(vrm.expressionManager?.expressionMap ?? {});
    const splitBlink = expressions.includes("blinkLeft") && expressions.includes("blinkRight");
    const defaultBlink = expressions.includes("blink") ? "blink" : splitBlink ? pairedBlink : "";
    const defaultMouth = expressions.includes("aa") ? "aa" : "";
    const capabilities = {
      mouth: Boolean(defaultMouth),
      blink: Boolean(defaultBlink),
      motion: true,
      sampling: "single" as const,
    };
    let mouthBinding = defaultMouth;
    let blinkBindings = defaultBlink === pairedBlink ? blinkExpressions.slice(1) : defaultBlink ? [defaultBlink] : [];
    const bones = Object.values(VRMHumanBoneName).filter((name) => vrm!.humanoid.getNormalizedBoneNode(name));
    const controls: VrmControls = { expressions, bones };
    const basePose = vrm.humanoid.getNormalizedPose();
    motions = createMotionPlayer(
      vrm.scene,
      bones.map((name) => vrm!.humanoid.getNormalizedBoneNode(name)!),
      expressions.map((name) => vrm!.expressionManager!.getExpression(name)!),
    );
    const bounds = new THREE.Box3().setFromObject(vrm.scene);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const eyeNodes = [VRMHumanBoneName.LeftEye, VRMHumanBoneName.RightEye]
      .map((name) => vrm!.humanoid.getRawBoneNode(name)?.getWorldPosition(new THREE.Vector3()))
      .filter((point): point is THREE.Vector3 => Boolean(point));
    const eyeLevel = eyeNodes.length
      ? eyeNodes.reduce((sum, point) => sum + point.y, 0) / eyeNodes.length
      : bounds.min.y + size.y * 0.9;
    const focus = new THREE.Vector3(center.x, eyeLevel, center.z);
    const corners = [bounds.min.x, bounds.max.x].flatMap((x) =>
      [bounds.min.y, bounds.max.y].flatMap((y) => [bounds.min.z, bounds.max.z].map((z) => new THREE.Vector3(x, y, z))),
    );
    const distance = Math.max(1, size.length() * 2);
    camera.near = 0.001;
    camera.far = distance * 4;
    let aspect = 1;
    const frameCamera = () => {
      const { yaw, pitch, zoom, panX, panY } = state.camera;
      camera.position.copy(
        new THREE.Vector3()
          .setFromSphericalCoords(distance, THREE.MathUtils.degToRad(90 - pitch), THREE.MathUtils.degToRad(yaw))
          .add(focus),
      );
      camera.lookAt(focus);
      camera.updateMatrixWorld();
      const projected = corners.map((point) => point.clone().applyMatrix4(camera.matrixWorldInverse));
      const xs = projected.map((point) => point.x);
      const ys = projected.map((point) => point.y);
      const left = Math.min(...xs),
        right = Math.max(...xs),
        bottom = Math.min(...ys),
        top = Math.max(...ys);
      const halfHeight = (Math.max((top - bottom) / 2, (right - left) / (2 * aspect), 0.05) * 1.1) / zoom;
      const x = (left + right) / (2 * zoom) + panX * size.y;
      const y = (top + bottom) / (2 * zoom) + panY * size.y;
      camera.left = x - halfHeight * aspect;
      camera.right = x + halfHeight * aspect;
      camera.bottom = y - halfHeight;
      camera.top = y + halfHeight;
      camera.updateProjectionMatrix();
      light.position.copy(camera.position);
      light.target.position.copy(focus);
      light.target.updateMatrixWorld();
    };
    frameCamera();
    const fit = (width: number, height: number) => {
      if (disposed || width <= 0 || height <= 0) return;
      renderer.setSize(width, height);
      aspect = width / height;
      frameCamera();
    };
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    mount.element.append(renderer.domElement);
    const clock = new THREE.Clock();
    const tick = () => {
      if (disposed || !vrm) return;
      const dt = Math.min(clock.getDelta(), 0.05);
      time += dt;
      motions!.update(dt);
      const em = vrm.expressionManager;
      if (mode !== "edit") {
        if (mouthBinding && (!motions!.playing || mouth > 0))
          em?.setValue(mouthBinding, Math.max(state.expressions[mouthBinding] ?? 0, mouth));
        if (!motions!.playing && !reduceMotion?.matches && blinkBindings.every((name) => !state.expressions[name])) {
          const phase = time % 4.3;
          const weight = phase < 0.16 ? Math.sin((phase / 0.16) * Math.PI) : 0;
          blinkBindings.forEach((name) => em?.setValue(name, weight));
        }
      }
      vrm.update(mode === "edit" ? 0 : dt);
      renderer.render(scene, camera);
      frame = requestAnimationFrame(tick);
    };
    tick();
    return {
      capabilities,
      controls,
      motionPlayback: "queued" as const,
      async apply(value, nextMode, abort, options) {
        abort.throwIfAborted();
        const next = parseState(value);
        const nextMouth = next.mouthExpression ?? defaultMouth;
        const nextBlink = next.blinkExpression ?? defaultBlink;
        if (nextMouth && !expressions.includes(nextMouth)) throw new Error(`Unknown expression: ${nextMouth}`);
        if (nextBlink && !(nextBlink === pairedBlink ? splitBlink : expressions.includes(nextBlink)))
          throw new Error(`Unknown expression: ${nextBlink}`);
        for (const name of Object.keys(next.expressions))
          if (!expressions.includes(name)) throw new Error(`Unknown expression: ${name}`);
        for (const name of Object.keys(next.bones))
          if (!bones.includes(name as VRMHumanBoneName)) throw new Error(`Unknown bone: ${name}`);
        const queued = nextMode === "play" && !options?.restartMotion && !reduceMotion?.matches;
        const loadSignal = queued ? signal : abort;
        const prepare = async () => {
          let clip = clips.get(next.motion);
          if (!next.motion || clip) return clip;
          const data = await load(mount.assetUrl(next.motion), loadSignal);
          try {
            const animation = data.userData.vrmAnimations?.[0];
            if (!animation) throw new Error("Missing VRMA animation");
            clip = createVRMAnimationClip(animation, vrm!);
            if (!clip.tracks.length) throw new Error("VRMA has no tracks matching this model");
          } finally {
            VRMUtils.deepDispose(data.scene);
          }
          loadSignal.throwIfAborted();
          if (disposed) return;
          if (clips.size >= 8) clips.delete(clips.keys().next().value!);
          clips.set(next.motion, clip);
          return clip;
        };
        await motions!.apply(
          prepare(),
          nextMode,
          () => {
            vrm!.humanoid.setNormalizedPose(basePose);
            expressions.forEach((name) => vrm!.expressionManager?.setValue(name, next.expressions[name] ?? 0));
            for (const [name, q] of Object.entries(next.bones))
              vrm!.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName)!.quaternion.fromArray(q);
          },
          () => {
            state = next;
            mode = nextMode;
            mouthBinding = nextMouth;
            blinkBindings = nextBlink === pairedBlink ? blinkExpressions.slice(1) : nextBlink ? [nextBlink] : [];
            capabilities.mouth = Boolean(nextMouth);
            capabilities.blink = blinkBindings.length > 0;
            if (nextMode === "edit") mouth = 0;
            frameCamera();
          },
          options?.restartMotion,
          reduceMotion?.matches,
        );
      },
      readState: () => structuredClone(state),
      setMouthOpen: (value) => {
        mouth = Number.isFinite(value) ? THREE.MathUtils.clamp(value, 0, 1) : 0;
      },
      resize: fit,
      dispose,
    };
  } catch (error) {
    dispose();
    throw error;
  }
}
