import { create } from "../../src/modules/character-visual/adapters/l2d/module";
import { neutralState } from "../../src/modules/character-visual/adapters/l2d/state";
import { loadSdk, type SdkModel, type SdkUserModel } from "../../src/modules/character-visual/adapters/l2d/sdk";
import { bindAvatarVoice, routeAvatarVoice } from "../../src/modules/character-visual/voiceRoute";

const abort = new AbortController();
// Observe actual rendered parameters in this local-only fixture, not saved state.
const sdk = await loadSdk(abort.signal);
sdk.initialize();
const probe = sdk.createModel();
// The pinned bridge creates a subclass of CubismUserModel for every instance.
const prototype = Object.getPrototypeOf(Object.getPrototypeOf(probe)) as SdkUserModel;
const loadModel = prototype.loadModel;
let observedModel: SdkModel;
prototype.loadModel = function (data, check) {
  loadModel.call(this, data, check);
  observedModel = this.getModel();
};
probe.release();
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
).finally(() => {
  prototype.loadModel = loadModel;
});
session.resize(600, 700);
await session.apply(neutralState(), "restore", abort.signal);
const unbind = bindAvatarVoice("Haru", session);
const readHeadAngles = () =>
  session.controls.parameters.flatMap((parameter, index) =>
    ["ParamAngleX", "ParamAngleY", "ParamAngleZ"].includes(parameter.id)
      ? [observedModel.getParameterValueByIndex(index)]
      : [],
  );
Object.assign(window, {
  l2dSmoke: { session, abort, readHeadAngles, routeVoice: (value: number) => routeAvatarVoice("Haru", value), unbind },
});
document.querySelector("#status")!.textContent = JSON.stringify({
  capabilities: session.capabilities,
  parameterCount: session.controls.parameters.length,
  expressions: session.controls.expressions,
  motions: session.controls.motions,
});
