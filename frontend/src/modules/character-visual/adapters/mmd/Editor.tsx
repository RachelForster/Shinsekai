import { useState } from "react";
import type { AvatarEditorProps } from "../../contracts";
import { useI18n } from "../../../../shared/i18n";
import { Button, PathDisplay, Select, TextInput } from "../../../../shared/ui";
import {
  cameraLimits,
  defaultCamera,
  neutralState,
  type MmdCameraState,
  type MmdControls,
  type MmdState,
} from "./state";
import "./Editor.css";

export function Editor({ session, value, onChange }: AvatarEditorProps<MmdState, MmdControls>) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const morphs = session.controls.morphs;
  const shown = morphs.filter((item) =>
    `${item.name} ${item.englishName}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );
  return (
    <fieldset className="mmd-editor">
      <legend>MMD / PMX</legend>
      {value.motion && (
        <div className="field-row field-row--stack">
          <PathDisplay path={value.motion} />
          <Button variant="ghost" onClick={() => onChange({ ...value, motion: "" })}>
            {t("character.avatar.clearMotion")}
          </Button>
        </div>
      )}
      <fieldset className="mmd-editor">
        <legend>{t("character.avatar.mmd.camera")}</legend>
        {(Object.keys(cameraLimits) as Array<keyof MmdCameraState>).map((key) => (
          <label key={key} className="field-row field-row--stack">
            <span className="field-row__label">
              {t(`character.avatar.mmd.camera.${key}`)}:{" "}
              {value.camera[key].toFixed(key === "yaw" || key === "pitch" ? 0 : 2)}
              {key === "yaw" || key === "pitch" ? "°" : key === "zoom" ? "×" : ""}
            </span>
            <span className="field-row__control">
              <input
                className="mmd-editor__morph"
                type="range"
                aria-label={t(`character.avatar.mmd.camera.${key}`)}
                {...cameraLimits[key]}
                value={value.camera[key]}
                onChange={(event) =>
                  onChange({ ...value, camera: { ...value.camera, [key]: Number(event.target.value) } })
                }
              />
            </span>
          </label>
        ))}
        <Button onClick={() => onChange({ ...value, camera: defaultCamera() })} variant="ghost">
          {t("character.avatar.mmd.resetCamera")}
        </Button>
      </fieldset>
      {!session.capabilities.mouth && <p role="status">{t("character.avatar.mmd.noMouth")}</p>}
      {!session.capabilities.blink && <p role="status">{t("character.avatar.mmd.noBlink")}</p>}
      <Button
        onClick={() =>
          onChange({ ...neutralState(value.mouthMorph, value.blinkMorph), camera: value.camera, motion: value.motion })
        }
        variant="ghost"
      >
        {t("character.avatar.mmd.reset")}
      </Button>
      {(["mouthMorph", "blinkMorph"] as const).map((key) => (
        <label key={key} className="field-row field-row--stack">
          <span className="field-row__label">
            {t(key === "mouthMorph" ? "character.avatar.mmd.mouthMorph" : "character.avatar.mmd.blinkMorph")}
          </span>
          <span className="field-row__control">
            <Select value={value[key]} onChange={(event) => onChange({ ...value, [key]: event.target.value })}>
              <option value="">{t("character.avatar.mmd.noMorph")}</option>
              {morphs.map((morph) => (
                <option key={morph.name} value={morph.name}>
                  {morph.name}
                  {morph.englishName && morph.englishName !== morph.name ? ` (${morph.englishName})` : ""}
                </option>
              ))}
            </Select>
          </span>
        </label>
      ))}
      <label className="field-row field-row--stack">
        <span className="field-row__label">{t("character.avatar.mmd.searchMorph")}</span>
        <span className="field-row__control">
          <TextInput value={search} onChange={(event) => setSearch(event.target.value)} />
        </span>
      </label>
      {shown.map((morph) => (
        <label key={morph.name} className="field-row field-row--stack">
          <span className="field-row__label">
            {morph.name}: {(value.morphs[morph.name] ?? 0).toFixed(2)}
          </span>
          <span className="field-row__control">
            <input
              className="mmd-editor__morph"
              type="range"
              aria-label={morph.name}
              min={0}
              max={1}
              step={0.01}
              value={value.morphs[morph.name] ?? 0}
              onChange={(event) =>
                onChange({ ...value, morphs: { ...value.morphs, [morph.name]: Number(event.target.value) } })
              }
            />
          </span>
        </label>
      ))}
    </fieldset>
  );
}
