import type { AvatarFormat } from "../../contracts";
import type { L2DControls, L2DState } from "./state";

const format: AvatarFormat<L2DState, L2DControls> = {
  id: "l2d",
  label: "Live2D Cubism",
  modelExtensions: [".model3.json"],
  runtime: {
    name: "Cubism SDK for Web",
    version: "5-r.4",
    downloadUrl: "https://www.live2d.com/en/sdk/download/web/",
    licenseUrls: [
      "https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html",
      "https://www.live2d.com/eula/live2d-open-software-license-agreement_en.html",
    ],
    compile: async (input, signal) => (await import("./compileRuntime")).compileRuntime(input, signal),
  },
  capabilities: { mouth: true, blink: true, motion: true, sampling: "none" },
  load: () => import("./module"),
};
export default format;
