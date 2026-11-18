import { AnimationClip, Group, NumberKeyframeTrack, Object3D } from "three";
import { describe, expect, it } from "vitest";
import { createMotionPlayer } from "../../../modules/character-visual/adapters/vrm/motion";

function rig() {
  const root = new Group();
  const head = new Object3D();
  head.name = "head";
  root.add(head);
  const player = createMotionPlayer(root, [head], []);
  const base = () => head.position.set(0, 0, 0);
  const clip = (start: number, end: number) =>
    new AnimationClip("motion", 1, [new NumberKeyframeTrack("head.position[x]", [0, 1], [start, end])]);
  return { player, head, base, clip };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

describe("VRM queued dialogue motions", () => {
  it("finishes each motion and starts subsequent requests from their first frame", async () => {
    const { player, head, base, clip } = rig();
    const started: number[] = [];
    await player.apply(clip(0, 10), "play", base, () => started.push(1));
    player.update(0.4);
    await player.apply(clip(20, 30), "play", base, () => started.push(2));
    await player.apply(clip(40, 50), "play", base, () => started.push(3));
    expect(head.position.x).toBeCloseTo(4);
    expect(started).toEqual([1]);
    player.update(0.6);
    expect(head.position.x).toBe(20);
    expect(started).toEqual([1, 2]);
    player.update(1);
    expect(head.position.x).toBe(40);
    expect(started).toEqual([1, 2, 3]);
    player.update(1);
    expect(head.position.x).toBe(50);
    expect(player.playing).toBe(false);
    player.dispose();
  });

  it("preserves order when a later motion finishes loading first", async () => {
    const { player, head, base, clip } = rig();
    const loading = deferred<AnimationClip>();
    await player.apply(clip(0, 10), "play", base);
    const second = player.apply(loading.promise, "play", base);
    await player.apply(clip(40, 50), "play", base);
    player.update(1);
    expect(head.position.x).toBe(10);
    loading.resolve(clip(20, 30));
    await second;
    expect(head.position.x).toBe(20);
    player.update(1);
    expect(head.position.x).toBe(40);
    player.dispose();
  });

  it("also queues a repeated action without restarting the current copy", async () => {
    const { player, head, base, clip } = rig();
    const motion = clip(0, 10);
    await player.apply(motion, "play", base);
    player.update(0.4);
    await player.apply(motion, "play", base);
    player.update(0.2);
    expect(head.position.x).toBeCloseTo(6);
    player.update(0.4);
    expect(head.position.x).toBe(0);
    player.dispose();
  });

  it("skips failed loads and starts the next ready request", async () => {
    const { player, head, base, clip } = rig();
    const loading = deferred<AnimationClip>();
    await player.apply(clip(0, 10), "play", base);
    const second = player.apply(loading.promise, "play", base);
    await player.apply(clip(40, 50), "play", base);
    player.update(1);
    loading.reject(new Error("failed download"));
    await expect(second).rejects.toThrow("failed download");
    expect(head.position.x).toBe(40);
    player.dispose();
  });

  it("changes a queued static pose only after the current motion ends", async () => {
    const { player, head, base, clip } = rig();
    await player.apply(clip(0, 10), "play", base);
    player.update(0.5);
    let started = false;
    await player.apply(
      undefined,
      "play",
      () => head.position.set(30, 0, 0),
      () => {
        started = true;
      },
    );
    expect(started).toBe(false);
    expect(head.position.x).toBeCloseTo(5);
    player.update(0.5);
    expect(started).toBe(true);
    expect(head.position.x).toBe(30);
    player.dispose();
  });

  it.each(["restore", "edit"] as const)("clears queued actions for %s and ignores late loads", async (mode) => {
    const { player, head, base, clip } = rig();
    const loading = deferred<AnimationClip>();
    await player.apply(clip(0, 10), "play", base);
    const queued = player.apply(loading.promise, "play", base);
    await player.apply(clip(40, 50), mode, base);
    loading.resolve(clip(20, 30));
    await queued;
    player.update(2);
    expect(head.position.x).toBe(mode === "restore" ? 50 : 40);
    player.dispose();
  });

  it("allows manual replay immediately and clears the previous queue", async () => {
    const { player, head, base, clip } = rig();
    const motion = clip(0, 10);
    await player.apply(motion, "play", base);
    player.update(0.5);
    await player.apply(clip(20, 30), "play", base);
    await player.apply(motion, "play", base, undefined, true);
    expect(head.position.x).toBe(0);
    player.update(1);
    expect(head.position.x).toBe(10);
    player.dispose();
  });

  it("clears pending requests on disposal and honors reduced motion", async () => {
    const { player, head, base, clip } = rig();
    await player.apply(clip(0, 10), "play", base, undefined, false, true);
    expect(head.position.x).toBe(10);
    const loading = deferred<AnimationClip>();
    const queued = player.apply(loading.promise, "play", base);
    player.dispose();
    const afterDispose = head.position.x;
    loading.resolve(clip(20, 30));
    await queued;
    player.update(2);
    expect(head.position.x).toBe(afterDispose);
  });
});
