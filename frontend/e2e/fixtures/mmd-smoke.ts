import { avatarAssetUrl } from "../../src/modules/character-visual/assetUrl";
import { create } from "../../src/modules/character-visual/adapters/mmd/module";
import { Engine } from "@babylonjs/core/Engines/engine";
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
  Object.assign(window, {
    mmdSmoke: {
      session,
      abort,
      hostInput,
      readHeadMatrix: () => readMatrix(headIndex ?? -1),
      readChestMatrix: () => readMatrix(chestIndex),
      readHeadPose: () => skeleton?.bones[headIndex]?.rotationQuaternion.asArray() ?? [],
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
