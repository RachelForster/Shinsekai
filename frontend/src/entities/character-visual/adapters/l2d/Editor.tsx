import type { AvatarEditorProps } from "../../contracts";
import type { L2DControls, L2DState } from "./state";

export function Editor({ session, value, onChange }: AvatarEditorProps<L2DState, L2DControls>) {
  return (
    <fieldset>
      <legend>Live2D</legend>
      {!session.capabilities.mouth && <p role="status">模型没有口型绑定 / No mouth binding</p>}
      {!session.capabilities.blink && <p role="status">模型没有眨眼绑定 / No eye binding</p>}
      <button type="button" onClick={() => onChange({ parameters: {}, expressions: [], motion: "" })}>
        重置 / Reset
      </button>
      {session.controls.parameters.map((parameter) => (
        <label key={parameter.id} style={{ display: "block" }}>
          {parameter.id}: {value.parameters[parameter.id] ?? parameter.default}
          <input
            type="range"
            aria-label={parameter.id}
            min={parameter.min}
            max={parameter.max}
            step={(parameter.max - parameter.min) / 200 || 0.01}
            value={value.parameters[parameter.id] ?? parameter.default}
            onChange={(event) =>
              onChange({ ...value, parameters: { ...value.parameters, [parameter.id]: Number(event.target.value) } })
            }
          />
        </label>
      ))}
      {session.controls.expressions.map((path) => (
        <label key={path} style={{ display: "block" }}>
          <input
            type="checkbox"
            checked={value.expressions.includes(path)}
            onChange={(event) =>
              onChange({
                ...value,
                expressions: event.target.checked
                  ? [...value.expressions, path]
                  : value.expressions.filter((item) => item !== path),
              })
            }
          />
          {path}
        </label>
      ))}
      <label>
        动作 / Motion{" "}
        <select value={value.motion} onChange={(event) => onChange({ ...value, motion: event.target.value })}>
          <option value="">无 / None</option>
          {session.controls.motions.map((path) => (
            <option key={path} value={path}>
              {path}
            </option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}
