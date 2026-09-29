import type { AvatarEditorProps } from "../../contracts";
import { useI18n } from "../../../../shared/i18n";
import { Button, Select, Switch } from "../../../../shared/ui";
import { neutralState, type L2DControls, type L2DState } from "./state";
import "./Editor.css";

export function Editor({ session, value, onChange }: AvatarEditorProps<L2DState, L2DControls>) {
  const { t } = useI18n();
  return (
    <fieldset className="l2d-editor">
      <legend>Live2D</legend>
      {!session.capabilities.mouth && (
        <p className="field-row__hint" role="status">
          {t("character.avatar.l2d.noMouth")}
        </p>
      )}
      {!session.capabilities.blink && (
        <p className="field-row__hint" role="status">
          {t("character.avatar.l2d.noBlink")}
        </p>
      )}
      <Button onClick={() => onChange(neutralState())} variant="ghost">
        {t("character.avatar.l2d.reset")}
      </Button>
      {session.controls.parameters.map((parameter) => (
        <label key={parameter.id} className="field-row field-row--stack">
          <span className="field-row__label">
            {parameter.id}: {value.parameters[parameter.id] ?? parameter.default}
          </span>
          <span className="field-row__control">
            <input
              className="l2d-editor__parameter"
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
          </span>
        </label>
      ))}
      {session.controls.expressions.map((path) => (
        <Switch
          key={path}
          checked={value.expressions.includes(path)}
          onChange={(event) =>
            onChange({
              ...value,
              expressions: event.target.checked
                ? [...value.expressions, path]
                : value.expressions.filter((item) => item !== path),
            })
          }
        >
          {path}
        </Switch>
      ))}
      <label className="field-row field-row--stack">
        <span className="field-row__label">{t("character.avatar.l2d.motion")}</span>
        <span className="field-row__control">
          <Select
            aria-label={t("character.avatar.l2d.motion")}
            value={value.motion}
            onChange={(event) => onChange({ ...value, motion: event.target.value })}
          >
            <option value="">{t("character.avatar.l2d.noMotion")}</option>
            {session.controls.motions.map((path) => (
              <option key={path} value={path}>
                {path}
              </option>
            ))}
          </Select>
        </span>
      </label>
    </fieldset>
  );
}
