import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "../../../modules/character-visual/adapters/mmd/Editor";
import {
  defaultCamera,
  neutralState,
  type MmdControls,
  type MmdState,
} from "../../../modules/character-visual/adapters/mmd/state";
import type { AvatarSession } from "../../../modules/character-visual/contracts";
import { I18nProvider } from "../../../shared/i18n";

const session: AvatarSession<MmdState, MmdControls> = {
  capabilities: { mouth: true, blink: true, motion: false, sampling: "none" },
  controls: { morphs: [{ name: "笑顔", englishName: "Smile", category: 2 }] },
  apply: async () => {},
  readState: neutralState,
  setMouthOpen: () => {},
  resize: () => {},
  dispose: () => {},
};
const state = {
  ...neutralState("あ", "まばたき"),
  morphs: { 笑顔: 0.5 },
  camera: { ...defaultCamera(), yaw: 20, zoom: 1.5 },
};
function view() {
  const onChange = vi.fn();
  render(
    <I18nProvider language="en">
      <Editor session={session} value={state} onChange={onChange} />
    </I18nProvider>,
  );
  return onChange;
}
afterEach(cleanup);

describe("MMD camera editor", () => {
  it.each([
    ["Horizontal rotation", "yaw", 45],
    ["Tilt", "pitch", -15],
    ["Zoom", "zoom", 2],
    ["Horizontal framing", "panX", 0.1],
    ["Vertical framing", "panY", -0.2],
  ])("edits %s without changing morphs or other view settings", (label, key, value) => {
    const onChange = view();
    fireEvent.change(screen.getByRole("slider", { name: String(label) }), { target: { value: String(value) } });
    expect(onChange).toHaveBeenCalledWith({ ...state, camera: { ...state.camera, [key]: value } });
  });
  it("resets camera and expression independently", () => {
    const onChange = view();
    fireEvent.click(screen.getByRole("button", { name: "Reset to eye-level front view" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...state, camera: defaultCamera() });
    fireEvent.click(screen.getByRole("button", { name: "Reset expression" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...state, morphs: {} });
  });
});
