import { avatarAssetUrl } from "../../src/modules/character-visual/assetUrl";
import { create } from "../../src/modules/character-visual/adapters/mmd/module";

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
  Object.assign(window, { mmdSmoke: { session, abort, hostInput } });
  document.querySelector("#status")!.textContent = JSON.stringify({
    capabilities: session.capabilities,
    bindings: session.readState(),
    morphs: session.controls.morphs.map((item) => item.name),
  });
} catch (error) {
  document.querySelector("#status")!.textContent = String(error);
}
