import type { AvatarFormat } from "../../contracts";
import type { MmdControls, MmdState } from "./state";

const format: AvatarFormat<MmdState, MmdControls> = {
  id: "mmd",
  label: "MMD (PMX)",
  modelExtensions: [".pmx"],
  stateExtensions: [".vpd", ".vmd"],
  capabilities: { mouth: true, blink: true, motion: true, sampling: "none" },
  load: () => import("./module"),
};

export default format;
