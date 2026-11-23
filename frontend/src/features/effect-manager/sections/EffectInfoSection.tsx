import { useCallback, useRef } from "react";
import { Palette, Trash2 } from "lucide-react";

import { DEFAULT_CHARACTER_COLOR } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import {
  Button,
  handleIdentityKeyDown,
  InlineIdentityConfirm,
  TextInput,
  type PageSectionProps,
} from "../../../shared/ui";
import type { EffectPageContext } from "../effectContext";

export function EffectInfoSection({ ctx, id }: PageSectionProps<EffectPageContext>) {
  const { t } = useI18n();
  const colorInputRef = useRef<HTMLInputElement | null>(null);
  const colorPickerValue = /^#[0-9a-fA-F]{6}$/.test(ctx.draft.color || "") ? ctx.draft.color : DEFAULT_CHARACTER_COLOR;
  const openColorPicker = useCallback(() => {
    colorInputRef.current?.click();
  }, []);

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("effect.section.info")}</h2>
        <div className="section__actions">
          <Button
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={ctx.requestDeleteEffect}
            variant="danger"
          >
            {t("common.delete")}
          </Button>
        </div>
      </div>
      <div className="form-grid form-grid--two effect-info-grid">
        <div className="field-row">
          <label className="field-row__label" htmlFor="effect-info-name-input">
            {t("effect.field.name")}
          </label>
          <span className="field-row__control">
            <div className="identity-field-group">
              <TextInput
                className={ctx.liveNameError ? "input--error" : ""}
                id="effect-info-name-input"
                onChange={(event) => ctx.updateField("name", event.target.value)}
                onKeyDown={(event) =>
                  handleIdentityKeyDown(event, {
                    canConfirm: !ctx.liveNameError && !ctx.identityPending,
                    disabled: ctx.identityPending,
                    isDirty: ctx.nameDirty,
                    onCancel: ctx.cancelIdentityName,
                    onConfirm: ctx.confirmIdentityName,
                  })
                }
                value={ctx.draft.name}
              />
              <InlineIdentityConfirm
                confirmDisabled={Boolean(ctx.liveNameError)}
                fieldLabel={t("effect.field.name")}
                loading={ctx.identityPending}
                onCancel={ctx.cancelIdentityName}
                onConfirm={ctx.confirmIdentityName}
                visible={ctx.nameDirty}
              />
            </div>
            {ctx.liveNameError ? <span className="field-error">{ctx.liveNameError}</span> : null}
          </span>
        </div>
        <label className="field-row">
          <span className="field-row__label">{t("effect.field.color")}</span>
          <span className="field-row__control">
            <div className="input-group effect-color-control">
              <TextInput onChange={(event) => ctx.updateField("color", event.target.value)} value={ctx.draft.color} />
              <span aria-hidden className="swatch" style={{ background: colorPickerValue }} />
              <Button icon={<Palette aria-hidden className="button__icon" />} onClick={openColorPicker} variant="ghost">
                {t("effect.action.pickColor")}
              </Button>
              <input
                className="visually-hidden"
                onChange={(event) => ctx.updateField("color", event.target.value)}
                ref={colorInputRef}
                type="color"
                value={colorPickerValue}
              />
            </div>
          </span>
        </label>
      </div>
    </section>
  );
}
