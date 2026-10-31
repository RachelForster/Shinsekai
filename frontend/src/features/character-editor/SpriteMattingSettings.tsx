import { useI18n } from "../../shared/i18n";
import type { SpriteMattingOptions } from "../../shared/platform/types";
import { Select, Switch } from "../../shared/ui";

interface Props {
  value: SpriteMattingOptions;
  onChange: (value: SpriteMattingOptions) => void;
  disabled: boolean;
  compact?: boolean;
}

export function SpriteMattingSettings({ value, onChange, disabled, compact = false }: Props) {
  const { t } = useI18n();
  return (
    <fieldset className="sprite-generation__matting-settings">
      <legend>{t("spriteMatting.settings")}</legend>
      <label className="field-row field-row--stack">
        <span className="field-row__label">{t("spriteMatting.model")}</span>
        <Select
          aria-label={t("spriteMatting.model")}
          disabled={disabled}
          value={value.mattingModel ?? "toonout"}
          onChange={(event) =>
            onChange({ ...value, mattingModel: event.target.value as SpriteMattingOptions["mattingModel"] })
          }
        >
          <option value="toonout">ToonOut</option>
          <option value="isnet-anime">ISNet Anime</option>
        </Select>
      </label>
      <p className="sprite-generation__hint">{t("spriteMatting.defaultHint")}</p>
      {!compact ? (
        <>
          <Switch
            checked={value.autoScreen ?? false}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, autoScreen: event.target.checked })}
          >
            {t("spriteMatting.autoScreen")}
          </Switch>
          <Switch
            checked={value.alphaMatting ?? false}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, alphaMatting: event.target.checked })}
          >
            {t("spriteMatting.alphaOption")}
          </Switch>
          <p className="sprite-generation__hint">{t("spriteMatting.optionHint")}</p>
        </>
      ) : null}
    </fieldset>
  );
}
