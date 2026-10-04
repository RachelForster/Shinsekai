import { avatarAssetUrl } from "../../src/modules/character-visual/assetUrl";
import { create } from "../../src/modules/character-visual/adapters/mmd/module";
import { Engine } from "@babylonjs/core/Engines/engine";
import { Matrix, Vector3 } from "@babylonjs/core/Maths/math.vector";
import { VertexBuffer } from "@babylonjs/core/Buffers/buffer";
import { bindAvatarVoice, routeAvatarVoice } from "../../src/modules/character-visual/voiceRoute";

const source = new URLSearchParams(location.search).get("source")!;
const modelUrl = `/api/avatar/file?${new URLSearchParams({ model_path: source, path: source.split(/[\\/]/).at(-1)! })}`;
const abort = new AbortController();
const hostInput = { mouseDowns: 0 };
document.querySelector("#model")!.addEventListener("mousedown", () => ++hostInput.mouseDowns);
try {
  const session = await create(
    {
      element: document.querySelector("#model")!,
      modelUrl,
      assetUrl: (path) => avatarAssetUrl(modelUrl, path),
      reportError: (error) => {
        document.querySelector("#status")!.textContent = error.message;
      },
    },
    abort.signal,
  );
  session.resize(600, 700);
  await session.apply(session.readState(), "restore", abort.signal);
  const unbind = bindAvatarVoice("MMD", session);
  const scene = Engine.Instances.at(-1)!.scenes[0];
  const root = scene.meshes.find((mesh) => mesh.metadata?.skeleton);
  const skeleton = root?.metadata.skeleton;
  const headIndex = skeleton?.bones.findIndex((bone: { name: string }) => ["頭", "head"].includes(bone.name));
  const findChest = (names: string[]) =>
    skeleton?.bones.findIndex((bone: { name: string }) =>
      names.includes(
        bone.name
          .trim()
          .toLowerCase()
          .replace(/[\s_]+/g, ""),
      ),
    ) ?? -1;
  const preferredChest = findChest(["上半身2", "上半身２", "upperbody2", "chest", "upperchest", "胸腔"]);
  const chestIndex = preferredChest >= 0 ? preferredChest : findChest(["上半身", "upperbody", "spine"]);
  const readMatrix = (index: number) => {
    if (!root || !skeleton || index < 0) return [];
    return Array.from(skeleton.getTransformMatrices(root).slice(index * 16, index * 16 + 16));
  };
  const readScreenPosition = (index: number) => {
    if (!root || !skeleton || index < 0 || !scene.activeCamera) return [];
    skeleton.getTransformMatrices(root);
    const world = skeleton.bones[index].getFinalMatrix().multiply(root.getWorldMatrix());
    const canvas = scene.getEngine().getRenderingCanvas()!;
    const viewport = scene.activeCamera.viewport.toGlobal(canvas.clientWidth, canvas.clientHeight);
    const point = Vector3.Project(Vector3.Zero(), world, scene.getTransformMatrix(), viewport);
    return [point.x, point.y];
  };
  // Probe actual eye-weighted geometry, rather than the stationary eye pivot.
  const eyeMarkers = new Map<string, { index: number; position: Vector3 }>();
  for (const names of [
    ["左目", "left eye", "eye_l", "eye.l"],
    ["右目", "right eye", "eye_r", "eye.r"],
  ]) {
    const index = skeleton?.bones.findIndex((bone: { name: string }) => names.includes(bone.name.toLowerCase())) ?? -1;
    if (index < 0) continue;
    const points: Vector3[] = [];
    for (const mesh of root?.metadata.meshes ?? []) {
      const positions = mesh.getVerticesData(VertexBuffer.PositionKind);
      const indices = mesh.getVerticesData(VertexBuffer.MatricesIndicesKind);
      const weights = mesh.getVerticesData(VertexBuffer.MatricesWeightsKind);
      if (!positions || !indices || !weights) continue;
      for (let v = 0; v < positions.length / 3; v++)
        if ([0, 1, 2, 3].some((k) => indices[v * 4 + k] === index && weights[v * 4 + k] > 0.99))
          points.push(Vector3.FromArray(positions, v * 3));
    }
    if (!points.length) continue;
    const front = Math.min(...points.map((p) => p.z));
    const surface = points.filter((p) => p.z < front + 0.02);
    const position = surface.reduce((sum, point) => sum.addInPlace(point), Vector3.Zero()).scale(1 / surface.length);
    eyeMarkers.set(skeleton.bones[index].name, { index, position });
  }
  const readEyeSurfacePosition = (name: string) => {
    const marker = eyeMarkers.get(name);
    if (!root || !marker || !scene.activeCamera) return [];
    const transform = Matrix.FromArray(skeleton.getTransformMatrices(root), marker.index * 16);
    const world = transform.multiply(root.getWorldMatrix());
    const canvas = scene.getEngine().getRenderingCanvas()!;
    const point = Vector3.Project(
      marker.position,
      world,
      scene.getTransformMatrix(),
      scene.activeCamera.viewport.toGlobal(canvas.clientWidth, canvas.clientHeight),
    );
    return [point.x, point.y];
  };
  const readEyeRotation = (name: string) => {
    const index = skeleton?.bones.findIndex((bone: { name: string }) => bone.name === name) ?? -1;
    if (!root || index < 0 || headIndex < 0) return [];
    skeleton.getTransformMatrices(root);
    const relative = skeleton.bones[index]
      .getFinalMatrix()
      .multiply(Matrix.Invert(skeleton.bones[headIndex].getFinalMatrix()));
    return [0, 1, 2, 4, 5, 6, 8, 9, 10].map((i) => relative.m[i]);
  };
  Object.assign(window, {
    mmdSmoke: {
      session,
      abort,
      hostInput,
      readHeadMatrix: () => readMatrix(headIndex ?? -1),
      readChestMatrix: () => readMatrix(chestIndex),
      readHeadScreenPosition: () => readScreenPosition(headIndex ?? -1),
      readChestScreenPosition: () => readScreenPosition(chestIndex),
      readBoneScreenPosition: (name: string) =>
        readScreenPosition(skeleton?.bones.findIndex((bone: { name: string }) => bone.name === name) ?? -1),
      readHeadPose: () => skeleton?.bones[headIndex]?.rotationQuaternion.asArray() ?? [],
      eyeNames: [...eyeMarkers.keys()],
      readEyeSurfacePosition,
      readEyeRotation,
      routeVoice: (value: number) => routeAvatarVoice("MMD", value),
      unbind,
    },
  });
  document.querySelector("#status")!.textContent = JSON.stringify({
    capabilities: session.capabilities,
    bindings: session.readState(),
    morphs: session.controls.morphs.map((item) => item.name),
  });
} catch (error) {
  document.querySelector("#status")!.textContent = String(error);
}
