import { ArcRotateCamera } from "@babylonjs/core/Cameras/arcRotateCamera";
import { Camera } from "@babylonjs/core/Cameras/camera";
import { DirectionalLight } from "@babylonjs/core/Lights/directionalLight";
import { HemisphericLight } from "@babylonjs/core/Lights/hemisphericLight";
import { Color3 } from "@babylonjs/core/Maths/math.color";
import { Vector3 } from "@babylonjs/core/Maths/math.vector";
import type { Scene } from "@babylonjs/core/scene";
import type { MmdCameraState } from "./state";

interface ModelGeometry {
  vertices: readonly { position: readonly number[] }[];
  bones: readonly { name: string; englishName: string; position: readonly number[] }[];
}

/** Format-owned camera and lighting; the shared host only supplies its viewport size. */
export function createView(scene: Scene, geometry: ModelGeometry) {
  if (!geometry.vertices.length) throw new Error("PMX has no vertices");
  const minimum = new Vector3(Infinity, Infinity, Infinity);
  const maximum = new Vector3(-Infinity, -Infinity, -Infinity);
  for (const vertex of geometry.vertices) {
    const point = Vector3.FromArray(vertex.position);
    if (![point.x, point.y, point.z].every(Number.isFinite)) throw new Error("Invalid PMX vertex position");
    minimum.minimizeInPlace(point);
    maximum.maximizeInPlace(point);
  }
  const size = maximum.subtract(minimum);
  const center = minimum.add(maximum).scale(0.5);
  const boneNamed = (names: string[]) =>
    geometry.bones.find(
      (bone) => names.includes(bone.name.toLowerCase()) || names.includes(bone.englishName.toLowerCase()),
    );
  const leftEye = boneNamed(["左目", "left eye", "eye_l", "eye.l"]);
  const rightEye = boneNamed(["右目", "right eye", "eye_r", "eye.r"]);
  const head = boneNamed(["頭", "head"]);
  const eyes =
    leftEye && rightEye
      ? Vector3.FromArray(leftEye.position).add(Vector3.FromArray(rightEye.position)).scale(0.5)
      : head
        ? Vector3.FromArray(head.position).add(new Vector3(0, size.y * 0.04, 0))
        : new Vector3(center.x, minimum.y + size.y * 0.9, center.z);
  const camera = new ArcRotateCamera(
    "mmd-camera",
    -Math.PI / 2,
    Math.PI / 2,
    Math.max(size.length() * 2, 1),
    eyes,
    scene,
  );
  camera.mode = Camera.ORTHOGRAPHIC_CAMERA;
  camera.minZ = Math.max(0.001, size.length() / 1000);
  camera.maxZ = Math.max(10, size.length() * 8);

  // A soft ambient fill avoids a black lower hemisphere. The key follows the
  // camera so adjusting yaw never turns the face away from its illumination.
  const fill = new HemisphericLight("mmd-fill", new Vector3(0, 1, 0), scene);
  fill.intensity = 0.65;
  fill.groundColor = new Color3(0.65, 0.65, 0.65);
  fill.specular = Color3.Black();
  const key = new DirectionalLight("mmd-key", new Vector3(0, 0, 1), scene);
  key.intensity = 0.8;
  key.specular = new Color3(0.08, 0.08, 0.08);
  const corners: Vector3[] = [];
  for (const x of [minimum.x, maximum.x])
    for (const y of [minimum.y, maximum.y]) for (const z of [minimum.z, maximum.z]) corners.push(new Vector3(x, y, z));

  return {
    update(view: MmdCameraState, width: number, height: number) {
      // Assign angles after the target is established: setTarget otherwise
      // rebuilds them from the previous position, introducing an upward tilt.
      camera.alpha = ((-90 + view.yaw) * Math.PI) / 180;
      camera.beta = ((90 - view.pitch) * Math.PI) / 180;
      const matrix = camera.getViewMatrix(true);
      const projected = corners.map((point) => Vector3.TransformCoordinates(point, matrix));
      const xs = projected.map((point) => point.x);
      const ys = projected.map((point) => point.y);
      const left = Math.min(...xs),
        right = Math.max(...xs),
        bottom = Math.min(...ys),
        top = Math.max(...ys);
      const aspect = Math.max(1, width) / Math.max(1, height);
      const halfHeight = (Math.max((top - bottom) / 2, (right - left) / (2 * aspect), 0.1) * 1.1) / view.zoom;
      // Zoom toward the eyes. Pan is expressed relative to model height so a
      // saved composition remains consistent in editor and chat viewports.
      const frameX = (left + right) / (2 * view.zoom) + view.panX * size.y;
      const frameY = (bottom + top) / (2 * view.zoom) + view.panY * size.y;
      camera.orthoTop = frameY + halfHeight;
      camera.orthoBottom = frameY - halfHeight;
      camera.orthoLeft = frameX - halfHeight * aspect;
      camera.orthoRight = frameX + halfHeight * aspect;
      key.direction = eyes.subtract(camera.position).normalize();
    },
  };
}
