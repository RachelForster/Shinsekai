import { afterEach, describe, expect, it } from "vitest";
import { NullEngine } from "@babylonjs/core/Engines/nullEngine";
import { Scene } from "@babylonjs/core/scene";
import { Vector3 } from "@babylonjs/core/Maths/math.vector";
import type { ArcRotateCamera } from "@babylonjs/core/Cameras/arcRotateCamera";
import type { DirectionalLight } from "@babylonjs/core/Lights/directionalLight";
import { createView } from "../../../modules/character-visual/adapters/mmd/view";
import { defaultCamera } from "../../../modules/character-visual/adapters/mmd/state";

const geometry = {
  vertices: [{ position: [-4, 0, -2] }, { position: [4, 20, 2] }],
  bones: [
    { name: "左目", englishName: "", position: [-0.5, 18, -1] },
    { name: "右目", englishName: "", position: [0.5, 18, -1] },
  ],
};
let engine: NullEngine;
function setup(model = geometry) {
  engine = new NullEngine();
  const scene = new Scene(engine);
  const view = createView(scene, model);
  return { scene, view, camera: scene.activeCamera as ArcRotateCamera };
}
afterEach(() => engine?.dispose());

describe("MMD view", () => {
  it("keeps the camera horizontal at eye height, even after resize", () => {
    const { camera, view } = setup();
    for (const [width, height] of [
      [600, 700],
      [300, 900],
      [1200, 500],
    ]) {
      view.update(defaultCamera(), width, height);
      expect(camera.target.asArray()).toEqual([0, 18, -1]);
      expect(camera.position.y).toBeCloseTo(18);
      expect(camera.beta).toBeCloseTo(Math.PI / 2);
      expect(camera.position.z).toBeLessThan(camera.target.z);
      for (const vertex of geometry.vertices) {
        const point = Vector3.TransformCoordinates(Vector3.FromArray(vertex.position), camera.getViewMatrix());
        expect(point.x).toBeGreaterThan(camera.orthoLeft!);
        expect(point.x).toBeLessThan(camera.orthoRight!);
        expect(point.y).toBeGreaterThan(camera.orthoBottom!);
        expect(point.y).toBeLessThan(camera.orthoTop!);
      }
    }
  });

  it("applies saved orbit, zoom and framing with the key light following the camera", () => {
    const { scene, camera, view } = setup();
    view.update(defaultCamera(), 600, 700);
    const originalHeight = camera.orthoTop! - camera.orthoBottom!;
    view.update({ ...defaultCamera(), zoom: 2, panX: 0.1 }, 600, 700);
    expect(camera.orthoTop! - camera.orthoBottom!).toBeCloseTo(originalHeight / 2);
    expect((camera.orthoLeft! + camera.orthoRight!) / 2).toBeCloseTo(2);
    for (const yaw of [-180, -90, 0, 45, 180]) {
      view.update({ ...defaultCamera(), yaw, pitch: 20 }, 600, 700);
      expect(camera.alpha).toBeCloseTo(((yaw - 90) * Math.PI) / 180);
      expect(camera.beta).toBeCloseTo((70 * Math.PI) / 180);
      const key = scene.getLightByName("mmd-key") as DirectionalLight;
      expect(Vector3.Dot(key.direction, camera.target.subtract(camera.position).normalize())).toBeCloseTo(1);
    }
  });

  it("falls back to model height when eye bones are missing", () => {
    const { camera, view } = setup({ ...geometry, bones: [] });
    view.update(defaultCamera(), 600, 700);
    expect(camera.position.y).toBeCloseTo(18);
  });
});
