import { useState } from "react";
import type { AvatarEditorProps } from "../../contracts";
import { useI18n } from "../../../../shared/i18n";
import { Button, PathDisplay, Select, TextInput } from "../../../../shared/ui";
import { ModelCameraControls } from "../../ModelCameraControls";
import { neutralState, type MmdControls, type MmdState } from "./state";
import "../../ModelEditor.css";

export function Editor({ session, value, onChange }: AvatarEditorProps<MmdState, MmdControls>) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const morphs = session.controls.morphs;
  const shown = morphs.filter((item) =>
    `${item.name} ${item.englishName}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );
  return (
    <fieldset className="model-editor">
      <legend>MMD / PMX</legend>
      {value.motion && (
        <div className="field-row field-row--stack">
          <PathDisplay path={value.motion} />
          <Button variant="ghost" onClick={() => onChange({ ...value, motion: "" })}>
            {t("character.avatar.clearMotion")}
          </Button>
        </div>
      )}
      <ModelCameraControls value={value.camera} onChange={(camera) => onChange({ ...value, camera })} />
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
              className="model-editor__slider"
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
