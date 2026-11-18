import type { AvatarFormat } from "../../contracts";
import type { VrmState, VrmControls } from "./state";
const format: AvatarFormat<VrmState, VrmControls> = {
  id: "vrm",
  label: "VRM",
  modelExtensions: [".vrm"],
  stateExtensions: [".vrma"],
  presetImportHintKey: "character.avatar.vrm.presetImportHint",
  capabilities: { mouth: true, blink: true, motion: true, sampling: "single" },
  load: () => import("./module"),
};
export default format;
