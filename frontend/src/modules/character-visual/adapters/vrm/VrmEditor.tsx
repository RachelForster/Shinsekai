import { Euler, Quaternion } from "three";
import { useState } from "react";
import type { AvatarEditorProps } from "../../contracts";
import { ModelCameraControls } from "../../ModelCameraControls";
import { blinkExpressions, pairedBlink, type VrmState, type VrmControls } from "./state";
import { useI18n } from "../../../../shared/i18n";
import { Button, PathDisplay, Select, TextInput } from "../../../../shared/ui";
import "../../ModelEditor.css";

export function Editor({ session, value, onChange }: AvatarEditorProps<VrmState, VrmControls>) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const expressions = session.controls.expressions;
  const splitBlink = expressions.includes("blinkLeft") && expressions.includes("blinkRight");
  const defaultBlink = expressions.includes("blink") ? "blink" : splitBlink ? pairedBlink : "";
  return (
    <fieldset className="model-editor">
      <legend>VRM</legend>
      {value.motion && (
        <div className="field-row field-row--stack">
          <PathDisplay path={value.motion} />
          <Button variant="ghost" onClick={() => onChange({ ...value, motion: "", motionTiming: undefined })}>
            {t("character.avatar.clearMotion")}
          </Button>
        </div>
      )}
      <ModelCameraControls value={value.camera} onChange={(camera) => onChange({ ...value, camera })} />
      {!session.capabilities.mouth && <p role="status">{t("character.avatar.vrm.noMouth")}</p>}
      {!session.capabilities.blink && <p role="status">{t("character.avatar.vrm.noBlink")}</p>}
      <Button variant="ghost" onClick={() => onChange({ ...value, expressions: {} })}>
        {t("character.avatar.mmd.reset")}
      </Button>
      {(["mouthExpression", "blinkExpression"] as const).map((key) => (
        <label key={key} className="field-row field-row--stack">
          <span className="field-row__label">{t(`character.avatar.vrm.${key}`)}</span>
          <span className="field-row__control">
            <Select
              value={
                value[key] ??
                (key === "mouthExpression" && expressions.includes("aa")
                  ? "aa"
                  : key === "blinkExpression"
                    ? defaultBlink
                    : "")
              }
              onChange={(event) => onChange({ ...value, [key]: event.target.value })}
            >
              <option value="">{t("character.avatar.mmd.noMorph")}</option>
              {key === "blinkExpression" && splitBlink && (
                <option value={pairedBlink}>{blinkExpressions.slice(1).join(" + ")}</option>
              )}
              {expressions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </Select>
          </span>
        </label>
      ))}
      <label className="field-row field-row--stack">
        <span className="field-row__label">{t("character.avatar.vrm.searchExpression")}</span>
        <span className="field-row__control">
          <TextInput value={search} onChange={(event) => setSearch(event.target.value)} />
        </span>
      </label>
      {expressions
        .filter((name) => name.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
        .map((name) => (
          <label key={name} className="field-row field-row--stack">
            <span className="field-row__label">
              {name}: {(value.expressions[name] ?? 0).toFixed(2)}
            </span>
            <span className="field-row__control">
              <input
                className="model-editor__slider"
                type="range"
                aria-label={name}
                min={0}
                max={1}
                step={0.01}
                value={value.expressions[name] ?? 0}
                onChange={(event) =>
                  onChange({
                    ...value,
                    expressions: { ...value.expressions, [name]: Number(event.target.value) },
                  })
                }
              />
            </span>
          </label>
        ))}
      <Button
        onClick={() =>
          onChange({
            ...value,
            bones: {
              ...value.bones,
              ...(session.controls.bones.includes("leftUpperArm")
                ? { leftUpperArm: [0, 0, Math.sin(0.6), Math.cos(0.6)] as [number, number, number, number] }
                : {}),
              ...(session.controls.bones.includes("rightUpperArm")
                ? { rightUpperArm: [0, 0, -Math.sin(0.6), Math.cos(0.6)] as [number, number, number, number] }
                : {}),
            },
          })
        }
      >
        {t("character.avatar.armsDown")}
      </Button>
      {session.controls.bones
        .filter((name) => ["head", "neck", "leftUpperArm", "rightUpperArm"].includes(name))
        .map((name) => {
          const q = new Quaternion(...(value.bones[name] ?? [0, 0, 0, 1]));
          const angle = new Euler().setFromQuaternion(q);
          return (
            <fieldset key={name} className="model-editor">
              <legend>{name}</legend>
              {(["x", "y", "z"] as const).map((axis) => (
                <label key={axis} className="field-row field-row--stack">
                  <span className="field-row__label">
                    {axis}: {angle[axis].toFixed(2)}
                  </span>
                  <span className="field-row__control">
                    <input
                      className="model-editor__slider"
                      type="range"
                      min="-1.5"
                      max="1.5"
                      step="0.01"
                      value={angle[axis]}
                      onChange={(e) => {
                        angle[axis] = Number(e.target.value);
                        const result = new Quaternion().setFromEuler(angle);
                        onChange({
                          ...value,
                          bones: { ...value.bones, [name]: [result.x, result.y, result.z, result.w] },
                        });
                      }}
                    />
                  </span>
                </label>
              ))}
            </fieldset>
          );
        })}
    </fieldset>
  );
}
