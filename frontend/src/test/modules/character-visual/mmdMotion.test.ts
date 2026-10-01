import { afterEach, describe, expect, it } from "vitest";
import { Bone } from "@babylonjs/core/Bones/bone";
import { Skeleton } from "@babylonjs/core/Bones/skeleton";
import { NullEngine } from "@babylonjs/core/Engines/nullEngine";
import { Matrix, Quaternion } from "@babylonjs/core/Maths/math.vector";
import { Mesh } from "@babylonjs/core/Meshes/mesh";
import { Scene } from "@babylonjs/core/scene";
import { MmdAnimation } from "babylon-mmd/esm/Loader/Animation/mmdAnimation";
import {
  MmdBoneAnimationTrack,
  MmdCameraAnimationTrack,
  MmdMorphAnimationTrack,
  MmdPropertyAnimationTrack,
} from "babylon-mmd/esm/Loader/Animation/mmdAnimationTrack";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import type { MmdSkinnedMesh } from "babylon-mmd/esm/Runtime/mmdMesh";
import { loadMotion, MmdMotionPlayer } from "../../../modules/character-visual/adapters/mmd/motion";
import { vmdBytes } from "../../fixtures/mmdMotion";

let engine: NullEngine;
function setup() {
  engine = new NullEngine();
  const scene = new Scene(engine);
  const mesh = new Mesh("model", scene);
  const skeleton = new Skeleton("rig", "rig", scene);
  const head = new Bone("head", skeleton, null, Matrix.Translation(0, 10, 0));
  const arm = new Bone("arm", skeleton, head, Matrix.Translation(0, 2, 0));
  mesh.skeleton = skeleton;
  mesh.metadata = {
    isMmdModel: true,
    header: {},
    skeleton,
    bones: ["head", "arm"].map((name, i) => ({
      name,
      parentBoneIndex: i - 1,
      transformOrder: i,
      flag: PmxObject.Bone.Flag.IsRotatable,
    })),
    morphs: [
      {
        name: "smile",
        type: PmxObject.Morph.Type.BoneMorph,
        indices: [0],
        positions: [0, 0, 0],
        rotations: [0, 0, 0, 1],
      },
    ],
    meshes: [mesh],
    materials: [],
    rigidBodies: [],
    joints: [],
  };
  const runtime = new MmdRuntime(scene, null);
  const model = runtime.createMmdModel(mesh as MmdSkinnedMesh, { buildPhysics: false, materialProxyConstructor: null });
  return { scene, head, arm, runtime, model, player: new MmdMotionPlayer(model) };
}
function animation(name = "head", yaw = 0.6) {
  const track = new MmdBoneAnimationTrack(name, 2);
  track.frameNumbers.set([0, 30]);
  track.rotations.set([...Quaternion.Identity().asArray(), ...Quaternion.RotationYawPitchRoll(yaw, 0, 0).asArray()]);
  track.rotationInterpolations.set([20, 107, 20, 107, 20, 107, 20, 107]);
  const morph = new MmdMorphAnimationTrack("smile", 2);
  morph.frameNumbers.set([0, 30]);
  morph.weights.set([0, 0.8]);
  return new MmdAnimation(
    "nod",
    [track],
    [],
    [morph],
    new MmdPropertyAnimationTrack(0, []),
    new MmdCameraAnimationTrack(0),
  );
}
afterEach(() => engine?.dispose());

describe("MMD SDK motion evaluation and smooth pose changes", () => {
  it("loads VMD binary through the real SDK loader", async () => {
    const { scene, head, player } = setup();
    const loaded = await loadMotion(scene, "nod.vmd", vmdBytes());
    expect(loaded.endFrame).toBe(30);
    player.set(player.bind(loaded), "play", false);
    for (let i = 0; i < 12; i++) player.sample(0.1);
    expect(head.rotationQuaternion.y).toBeCloseTo(Math.sin(0.3), 6);
  });
  it("plays once at 30 fps, holds final pose, and restores without replay", () => {
    const { head, model, player, runtime } = setup();
    const bound = player.bind(animation());
    player.set(bound, "play", false);
    expect(player.controlsMorph("smile")).toBe(true);
    expect(player.controlsMorph("blink")).toBe(false);
    for (let i = 0; i < 10; i++) {
      model.morph.resetMorphWeights();
      player.sample(0.05);
    }
    expect(head.rotationQuaternion.y).toBeGreaterThan(0.1);
    expect(head.rotationQuaternion.y).toBeLessThan(0.3);
    expect(model.morph.getMorphWeight("smile")).toBeCloseTo(0.4);
    for (let i = 0; i < 50; i++) player.sample(0.05);
    const final = head.rotationQuaternion.clone();
    expect(final.y).toBeCloseTo(Quaternion.RotationYawPitchRoll(0.6, 0, 0).y, 6);
    expect(final.w).toBeCloseTo(Quaternion.RotationYawPitchRoll(0.6, 0, 0).w, 6);
    player.set(bound, "restore", false);
    player.sample(0);
    expect(head.rotationQuaternion.asArray()).toEqual(final.asArray());
    runtime.beforePhysics(16);
    runtime.afterPhysics();
    expect(Array.from(model.worldTransformMatrices).some((value) => Math.abs(value - 1) > 0.1)).toBe(true);
  });

  it("crossfades from the current pose and clears bones absent from the next preset", () => {
    const { head, arm, player } = setup();
    player.set(player.bind(animation()), "restore", false);
    player.sample(0);
    const original = head.rotationQuaternion.clone();
    player.set(player.bind(animation("arm", -0.4)), "play", true);
    player.sample(0);
    expect(head.rotationQuaternion.asArray()).toEqual(original.asArray());
    player.sample(0.1);
    expect(head.rotationQuaternion.y).toBeGreaterThan(0);
    expect(head.rotationQuaternion.y).toBeLessThan(original.y);
    for (let i = 0; i < 12; i++) player.sample(0.1);
    expect(head.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    expect(arm.rotationQuaternion.y).toBeLessThan(-0.1);
    player.set(null, "play", true);
    expect(player.controlsMorph("smile")).toBe(false);
    expect(player.hasPose).toBe(true);
    for (let i = 0; i < 4; i++) player.sample(0.1);
    expect(arm.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    expect(player.hasPose).toBe(false);
  });

  it("loads UTF-8 VPD and holds its offset pose in edit mode", async () => {
    const { scene, head, player } = setup();
    const text = "Vocaloid Pose Data file\n\nmodel.osm;\n1;\nBone0{head\n0,1,0;\n0,0.258819,0,0.965926;\n}\n";
    const data = new TextEncoder().encode(text).buffer;
    const loaded = await loadMotion(scene, "pose.VPD", data);
    player.set(player.bind(loaded), "edit", false);
    player.sample(0);
    expect(head.position.y).toBe(11);
    const pose = head.rotationQuaternion.asArray();
    for (let i = 0; i < 100; i++) player.sample(0.05);
    expect(head.rotationQuaternion.asArray()).toEqual(pose);
    expect(head.position.y).toBe(11);
  });

  it("rejects presets without matching tracks", () => {
    const { player } = setup();
    const empty = new MmdAnimation(
      "unknown",
      [],
      [],
      [],
      new MmdPropertyAnimationTrack(0, []),
      new MmdCameraAnimationTrack(0),
    );
    expect(() => player.bind(empty)).toThrow("matching");
  });
  it("keeps the motion timeline in real time even at a low render frame rate", () => {
    const { head, player } = setup();
    player.set(player.bind(animation()), "play", true);
    player.sample(1.5);
    expect(head.rotationQuaternion.y).toBeCloseTo(Math.sin(0.3), 6);
  });
});
