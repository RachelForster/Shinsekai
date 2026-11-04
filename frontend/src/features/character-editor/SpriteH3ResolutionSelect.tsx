import { useI18n } from "../../shared/i18n";
import type { H3SpriteResolution } from "../../shared/platform/types";
import { Select } from "../../shared/ui";

export function SpriteH3ResolutionSelect({
  value,
  onChange,
  disabled,
}: {
  value: H3SpriteResolution;
  onChange: (value: H3SpriteResolution) => void;
  disabled: boolean;
}) {
  const { t } = useI18n();
  return (
    <label className="field-row field-row--stack">
      <span className="field-row__label">{t("spriteGeneration.h3Resolution")}</span>
      <Select
        aria-label={t("spriteGeneration.h3Resolution")}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value as H3SpriteResolution)}
      >
        <option value="workflow">{t("spriteGeneration.resolutionWorkflow")}</option>
        <option value="hd">{t("spriteGeneration.resolutionHd")}</option>
        <option value="native">{t("spriteGeneration.resolutionNative")}</option>
      </Select>
      <p className="sprite-generation__hint">{t("spriteGeneration.resolutionHint")}</p>
    </label>
  );
}
