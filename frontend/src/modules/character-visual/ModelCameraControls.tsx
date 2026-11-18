import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui";
import { cameraLimits, defaultCamera, type ModelCamera } from "./modelCamera";

export function ModelCameraControls({ value, onChange }: { value: ModelCamera; onChange(value: ModelCamera): void }) {
  const { t } = useI18n();
  return (
    <fieldset className="model-editor">
      <legend>{t("character.avatar.mmd.camera")}</legend>
      {(Object.keys(cameraLimits) as Array<keyof ModelCamera>).map((key) => (
        <label key={key} className="field-row field-row--stack">
          <span className="field-row__label">
            {t(`character.avatar.mmd.camera.${key}`)}: {value[key].toFixed(key === "yaw" || key === "pitch" ? 0 : 2)}
            {key === "yaw" || key === "pitch" ? "°" : key === "zoom" ? "×" : ""}
          </span>
          <span className="field-row__control">
            <input
              className="model-editor__slider"
              type="range"
              aria-label={t(`character.avatar.mmd.camera.${key}`)}
              {...cameraLimits[key]}
              value={value[key]}
              onChange={(event) => onChange({ ...value, [key]: Number(event.target.value) })}
            />
          </span>
        </label>
      ))}
      <Button onClick={() => onChange(defaultCamera())} variant="ghost">
        {t("character.avatar.mmd.resetCamera")}
      </Button>
    </fieldset>
  );
}
