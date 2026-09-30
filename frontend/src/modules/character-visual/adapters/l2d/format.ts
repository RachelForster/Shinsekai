import type { AvatarFormat } from "../../contracts";
import type { L2DControls, L2DState } from "./state";

const format: AvatarFormat<L2DState, L2DControls> = {
  id: "l2d",
  label: "Live2D Cubism",
  modelExtensions: [".model3.json"],
  capabilities: { mouth: true, blink: true, motion: true, sampling: "none" },
  load: () => import("./module"),
};
export default format;
