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
  const readHeadMatrix = () => {
    if (!root || !skeleton || headIndex < 0) return [];
    return Array.from(skeleton.getTransformMatrices(root).slice(headIndex * 16, headIndex * 16 + 16));
  };
  Object.assign(window, {
    mmdSmoke: {
      session,
      abort,
      hostInput,
      readHeadMatrix,
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
