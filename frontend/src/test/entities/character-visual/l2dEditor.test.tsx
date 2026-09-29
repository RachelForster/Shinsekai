import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Editor } from "../../../entities/character-visual/adapters/l2d/Editor";
import { neutralState, type L2DControls, type L2DState } from "../../../entities/character-visual/adapters/l2d/state";
import type { AvatarSession } from "../../../entities/character-visual/contracts";
import { I18nProvider } from "../../../shared/i18n";

const session: AvatarSession<L2DState, L2DControls> = {
  capabilities: { mouth: false, blink: false, motion: true, sampling: "none" },
  controls: {
    parameters: [{ id: "ParamAngleX", min: -30, max: 30, default: 0 }],
    expressions: ["expressions/smile.exp3.json"],
    motions: ["motions/wave.motion3.json"],
  },
  apply: async () => {},
  readState: neutralState,
  setMouthOpen: () => {},
  resize: () => {},
  dispose: () => {},
};

function view(value = neutralState()) {
  const onChange = vi.fn();
  render(
    <I18nProvider language="en">
      <Editor session={session} value={value} onChange={onChange} />
    </I18nProvider>,
  );
  return onChange;
}

afterEach(cleanup);

describe("Live2D shared editor controls", () => {
  it("uses the shared motion dropdown without changing other state fields", () => {
    const value = { ...neutralState(), parameters: { ParamAngleX: 7 } };
    const onChange = view(value);
    const select = screen.getByRole("combobox", { name: "Motion" });
    expect(select.tagName).toBe("BUTTON");
    fireEvent.click(select);
    fireEvent.click(screen.getByRole("option", { name: "motions/wave.motion3.json" }));
    expect(onChange).toHaveBeenCalledWith({ ...value, motion: "motions/wave.motion3.json" });
  });

  it("uses the shared expression switch to add and remove an expression", () => {
    const onChange = view();
    const checkbox = screen.getByRole("checkbox", { name: "expressions/smile.exp3.json" });
    expect(checkbox).toHaveClass("switch__input");
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith({ ...neutralState(), expressions: session.controls.expressions });
    cleanup();
    const remove = view({ ...neutralState(), expressions: session.controls.expressions });
    fireEvent.click(screen.getByRole("checkbox", { name: "expressions/smile.exp3.json" }));
    expect(remove).toHaveBeenCalledWith(neutralState());
  });

  it("updates a parameter while preserving expressions and motion", () => {
    const value = { parameters: {}, expressions: session.controls.expressions, motion: session.controls.motions[0] };
    const onChange = view(value);
    fireEvent.change(screen.getByRole("slider", { name: "ParamAngleX" }), { target: { value: "12" } });
    expect(onChange).toHaveBeenCalledWith({ ...value, parameters: { ParamAngleX: 12 } });
  });

  it("uses the shared reset button and keeps capability warnings", () => {
    const onChange = view({
      parameters: { ParamAngleX: 10 },
      expressions: session.controls.expressions,
      motion: session.controls.motions[0],
    });
    expect(screen.getAllByRole("status")).toHaveLength(2);
    const reset = screen.getByRole("button", { name: "Reset" });
    expect(reset).toHaveClass("button");
    fireEvent.click(reset);
    expect(onChange).toHaveBeenCalledWith(neutralState());
  });
});
