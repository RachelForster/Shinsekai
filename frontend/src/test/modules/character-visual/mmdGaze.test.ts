import { afterEach, describe, expect, it } from "vitest";
import { Bone } from "@babylonjs/core/Bones/bone";
import { Skeleton } from "@babylonjs/core/Bones/skeleton";
import { NullEngine } from "@babylonjs/core/Engines/nullEngine";
import { Matrix, Quaternion, Vector3 } from "@babylonjs/core/Maths/math.vector";
import { Mesh } from "@babylonjs/core/Meshes/mesh";
import { Scene } from "@babylonjs/core/scene";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import type { MmdSkinnedMesh } from "babylon-mmd/esm/Runtime/mmdMesh";
import { GazeMotion, createGazePose } from "../../../modules/character-visual/adapters/mmd/gaze";

const flag = PmxObject.Bone.Flag;
const neutral = { yaw: 0, pitch: 0, head: { yaw: 0, pitch: 0, roll: 0 }, blink: false };
const radians = Math.PI / 180;
let engine: NullEngine;
const advance = (motion: GazeMotion, seconds: number, fps = 60) => {
  let result = neutral;
  for (let i = 0; i < Math.round(seconds * fps); i++) result = motion.sample(1 / fps);
  return result;
};

function setup(names = ["頭", "両目", "左目", "右目"], eyeFlag = flag.IsRotatable | flag.HasAppendRotate) {
  engine = new NullEngine();
  const scene = new Scene(engine);
  const root = new Mesh("model", scene);
  const skeleton = new Skeleton("rig", "rig", scene);
  const head = new Bone(names[0], skeleton, null, Matrix.Translation(0, 10, 0));
  const controller = new Bone(names[1], skeleton, head, Matrix.Translation(0, 3, 0));
  const left = new Bone(names[2], skeleton, head, Matrix.Translation(0.5, 1, -0.5));
  const right = new Bone(names[3], skeleton, head, Matrix.Translation(-0.5, 1, -0.5));
  const bones = names.map((name, i) => ({
    name,
    englishName: "",
    parentBoneIndex: i === 0 ? -1 : 0,
    transformOrder: i,
    flag: i < 2 ? flag.IsRotatable : eyeFlag,
    appendTransform: i < 2 ? undefined : { parentIndex: 1, ratio: 0.5 },
  }));
  root.skeleton = skeleton;
  root.metadata = {
    isMmdModel: true,
    header: {},
    skeleton,
    bones,
    morphs: [],
    meshes: [root],
    materials: [],
    rigidBodies: [],
    joints: [],
  };
  const runtime = new MmdRuntime(scene, null);
  const model = runtime.createMmdModel(root as MmdSkinnedMesh, { buildPhysics: false, materialProxyConstructor: null });
  return { head, controller, left, right, bones, model, runtime };
}
afterEach(() => engine?.dispose());

describe("MMD conversational gaze", () => {
  it("lets the eyes lead the head in both directions while keeping the intended gaze stable", () => {
    const motion = new GazeMotion(() => 0.2);
    motion.setAttention("thinking");
    const early = advance(motion, 0.55);
    expect(Math.abs(early.yaw)).toBeGreaterThan(0.02);
    expect(early.head.yaw).toBe(0);
    const following = advance(motion, 0.5);
    expect(Math.abs(following.head.yaw)).toBeGreaterThan(0.01);
    const held = advance(motion, 1);
    expect(following.yaw + following.head.yaw).toBeCloseTo(held.yaw + held.head.yaw, 4);
    motion.setAttention("responding");
    const returnedEyes = advance(motion, 0.16);
    expect(Math.abs(returnedEyes.head.yaw)).toBeGreaterThan(0.01);
    expect(Math.abs(returnedEyes.yaw + returnedEyes.head.yaw)).toBeLessThan(0.01);
    expect(Math.sign(returnedEyes.yaw)).not.toBe(Math.sign(returnedEyes.head.yaw));
    const returnedHead = advance(motion, 1.5);
    expect(Math.abs(returnedHead.head.yaw)).toBeLessThan(0.0001);
  });

  it("keeps small glances eye-only and lets authored head poses retain the whole gaze offset", () => {
    const small = new GazeMotion(() => 0.2);
    const sample = advance(small, 3.5);
    expect(Math.abs(sample.yaw)).toBeGreaterThan(0.01);
    expect(sample.head).toEqual(neutral.head);
    const held = new GazeMotion(() => 0.2);
    held.setAttention("thinking");
    let result = neutral;
    for (let i = 0; i < 90; i++) result = held.sample(1 / 60, true, false);
    expect(Math.abs(result.yaw)).toBeGreaterThan(3 * radians);
    expect(result.head).toEqual(neutral.head);
  });

  it("requests a blink on meaningful target changes, without repeating during a held look", () => {
    const motion = new GazeMotion(() => 0.2);
    motion.setAttention("thinking");
    const samples = Array.from({ length: 240 }, () => motion.sample(1 / 60));
    expect(samples.filter((sample) => sample.blink)).toHaveLength(2);
  });

  it("aims both eye rays at the same distant point, including while facing forward", () => {
    const { left, right, bones, model } = setup();
    const gaze = createGazePose(model.runtimeBones, bones);
    for (const offset of [
      { yaw: 0, pitch: 0 },
      { yaw: 0.08, pitch: 0.04 },
    ]) {
      gaze.apply(offset);
      const targetZ = -0.5 - Math.cos(offset.yaw) * Math.cos(offset.pitch) * 40;
      const intersections = [left, right].map((bone) => {
        const origin = Matrix.Invert(bone.getAbsoluteInverseBindMatrix()).getTranslation();
        const direction = Vector3.TransformNormal(
          new Vector3(0, 0, -1),
          Matrix.FromQuaternionToRef(bone.rotationQuaternion, Matrix.Identity()),
        );
        return origin.add(direction.scale((targetZ - origin.z) / direction.z));
      });
      expect(Vector3.Distance(intersections[0], intersections[1])).toBeLessThan(0.00001);
      expect(intersections[0].x).toBeCloseTo(-Math.sin(offset.yaw) * Math.cos(offset.pitch) * 40, 5);
      gaze.restore();
    }
  });
  it("holds small idle glances with quiet intervals and independent direction/timing", () => {
    const motion = new GazeMotion(() => 0.2);
    expect(advance(motion, 2)).toEqual(neutral);
    const samples = Array.from({ length: 900 }, () => motion.sample(1 / 60));
    expect(samples.some((p) => p.yaw < -0.015)).toBe(true);
    expect(samples.slice(200).some((p) => Math.abs(p.yaw) < 0.0001)).toBe(true);
    for (let i = 1; i < samples.length; i++) {
      expect(Math.abs(samples[i].yaw)).toBeLessThanOrEqual(1.8 * radians);
      expect(Math.abs(samples[i].pitch)).toBeLessThanOrEqual(0.7 * radians);
      expect(Math.abs(samples[i].yaw - samples[i - 1].yaw)).toBeLessThan(0.006);
    }
    expect(advance(new GazeMotion(() => 0.2), 3.5).yaw).toBeLessThan(0);
    expect(advance(new GazeMotion(() => 0.8), 3.5)).toEqual(neutral);
  });

  it("acknowledges first, holds one thought, and looks back even during a long wait", () => {
    const motion = new GazeMotion(() => 0.2);
    motion.setAttention("thinking");
    expect(advance(motion, 0.4)).toEqual(neutral);
    const thought = advance(motion, 0.6);
    expect(Math.abs(thought.yaw + thought.head.yaw)).toBeGreaterThan(3 * radians);
    motion.setAttention("thinking");
    const returned = advance(motion, 3);
    expect(Math.abs(returned.yaw + returned.head.yaw)).toBeLessThan(0.0001);
    expect(Math.abs(advance(motion, 20).yaw)).toBeLessThan(0.0001);
  });

  it.each(["idle", "responding"] as const)("returns smoothly on %s and prioritizes speech pauses", (attention) => {
    const motion = new GazeMotion(() => 0.2);
    motion.setAttention("thinking");
    const before = advance(motion, 1);
    motion.setAttention(attention);
    const first = motion.sample(1 / 60);
    expect(Math.abs(first.yaw)).toBeLessThan(Math.abs(before.yaw));
    expect(Math.abs(first.yaw)).toBeGreaterThan(0);
    const returned = advance(motion, 0.7);
    expect(Math.abs(returned.yaw + returned.head.yaw)).toBeLessThan(0.0001);
    motion.setAttention("thinking");
    advance(motion, 2);
    motion.setSpeechLevel(0.5);
    advance(motion, 0.5);
    motion.setSpeechLevel(0);
    const speech = advance(motion, 0.2);
    expect(Math.abs(speech.yaw + speech.head.yaw)).toBeLessThan(0.0001);
  });

  it("pauses for editing/reduced motion and uses elapsed time across frame rates", () => {
    const sample = (fps: number) => {
      const motion = new GazeMotion(() => 0.2);
      motion.setAttention("thinking");
      return advance(motion, 2, fps);
    };
    expect(sample(30).yaw).toBeCloseTo(sample(120).yaw, 6);
    const motion = new GazeMotion(() => 0.2);
    motion.setAttention("thinking");
    advance(motion, 1);
    expect(motion.sample(0.05, false)).toEqual(neutral);
    expect(advance(motion, 0.3)).toEqual(neutral);
    const resumed = advance(motion, 0.7);
    expect(Math.abs(resumed.yaw)).toBeGreaterThan(0.02);
    expect(Math.abs(resumed.head.yaw)).toBeGreaterThan(0.01);
    for (const dt of [NaN, Infinity, -1, 0]) expect(new GazeMotion().sample(dt)).toEqual(neutral);
  });

  it.each([
    flag.IsRotatable | flag.HasAppendRotate,
    flag.IsRotatable | flag.HasAppendRotate | flag.TransformAfterPhysics,
  ])(
    "drives both eyes through MMD append solvers without doubling the controller or changing the saved pose (%s)",
    (eyeFlag) => {
      const { head, controller, left, right, bones, model, runtime } = setup(undefined, eyeFlag);
      const gaze = createGazePose(model.runtimeBones, bones);
      controller.rotationQuaternion = Quaternion.RotationYawPitchRoll(0.2, 0.05, 0);
      const controllerPose = controller.rotationQuaternion.asArray();
      runtime.beforePhysics(16);
      runtime.afterPhysics();
      const original = Array.from(model.runtimeBones[2].worldMatrix);
      expect(gaze.boneNames).toEqual(["左目", "右目", "両目"]);
      for (let i = 0; i < 100; i++) {
        gaze.apply({ yaw: 0.05, pitch: 0.02 });
        expect(left.rotationQuaternion.y).toBeGreaterThan(0);
        expect(right.rotationQuaternion.y).toBeGreaterThan(0);
        expect(controller.rotationQuaternion.asArray()).toEqual(controllerPose);
        runtime.beforePhysics(16);
        runtime.afterPhysics();
        expect(Array.from(model.runtimeBones[2].worldMatrix)).not.toEqual(original);
        gaze.restore();
        expect(left.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
        expect(right.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
        expect(head.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
      }
      runtime.beforePhysics(16);
      runtime.afterPhysics();
      expect(Array.from(model.runtimeBones[2].worldMatrix)).toEqual(original);
    },
  );

  it("recognizes English eye names and skips incomplete pairs", () => {
    const { left, right, bones, model } = setup(["head", "eyes", "custom-left", "custom-right"]);
    bones[2].englishName = "Eye_L";
    bones[3].englishName = "Eye_R";
    const gaze = createGazePose(model.runtimeBones, bones);
    gaze.apply({ yaw: 0.03, pitch: 0 });
    expect(left.rotationQuaternion.y).toBeGreaterThan(0);
    expect(right.rotationQuaternion.y).toBeGreaterThan(0);
    gaze.restore();
    gaze.apply({ yaw: NaN, pitch: 0 });
    expect(left.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    bones[3].englishName = "unknown";
    const missing = createGazePose(model.runtimeBones, bones);
    missing.apply({ yaw: 0.03, pitch: 0 });
    expect(missing.boneNames).toEqual([]);
    expect(left.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
  });

  it.each([0, flag.IsRotatable | flag.HasAxisLimit])("does not turn restricted eyes (%s)", (eyeFlag) => {
    const { left, right, bones, model } = setup(undefined, eyeFlag);
    const gaze = createGazePose(model.runtimeBones, bones);
    gaze.apply({ yaw: 0.03, pitch: 0.02 });
    expect(gaze.boneNames).toEqual([]);
    expect(left.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    expect(right.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
  });
});
