import { create } from "../../src/modules/character-visual/adapters/l2d/module";
import { neutralState } from "../../src/modules/character-visual/adapters/l2d/state";

const abort = new AbortController();
const session = await create(
  {
    element: document.querySelector("#model")!,
    modelUrl: "/live2d/models/Haru/Haru.model3.json",
    assetUrl: (path) => `/live2d/models/Haru/${path}`,
    reportError: (error) => {
      document.querySelector("#status")!.textContent = error.message;
    },
  },
  abort.signal,
);
session.resize(600, 700);
await session.apply(neutralState(), "restore", abort.signal);
Object.assign(window, { l2dSmoke: { session, abort } });
document.querySelector("#status")!.textContent = JSON.stringify({
  capabilities: session.capabilities,
  parameterCount: session.controls.parameters.length,
  expressions: session.controls.expressions,
  motions: session.controls.motions,
});
