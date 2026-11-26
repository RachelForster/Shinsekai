import { Languages, Trash2 } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import {
  AsyncButton,
  Button,
  handleIdentityKeyDown,
  InlineIdentityConfirm,
  TextInput,
  type PageSectionProps,
} from "../../../shared/ui";
import type { BackgroundPageContext } from "../backgroundContext";
import { useBackgroundInfoController } from "../controllers/useBackgroundInfoController";

export function BackgroundInfoSection({ ctx, id }: PageSectionProps<BackgroundPageContext>) {
  const { t } = useI18n();
  const info = useBackgroundInfoController(ctx);

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("background.section.info")}</h2>
        <div className="page__actions">
          <AsyncButton
            icon={<Languages aria-hidden className="button__icon" />}
            loading={info.translatePending}
            onClick={info.handleTranslate}
            variant="ghost"
          >
            {t("background.action.aiTranslate")}
          </AsyncButton>
          <Button
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={ctx.requestDeleteBackground}
            variant="danger"
          >
            {t("common.delete")}
          </Button>
        </div>
      </div>
      <div className="form-grid form-grid--two">
        <div className="field-row">
          <label className="field-row__label" htmlFor="background-info-name-input">
            {t("background.field.name")}
          </label>
          <span className="field-row__control">
            <div className="identity-field-group">
              <TextInput
                className={ctx.liveNameError ? "input--error" : ""}
                id="background-info-name-input"
                onChange={(event) => ctx.updateField("name", event.target.value)}
                onKeyDown={(event) =>
                  handleIdentityKeyDown(event, {
                    canConfirm: !ctx.liveNameError && ctx.identitySavingField === null,
                    disabled: ctx.identitySavingField !== null,
                    isDirty: ctx.nameDirty,
                    onCancel: () => ctx.cancelIdentityField("name"),
                    onConfirm: () => ctx.confirmIdentityField("name"),
                  })
                }
                value={ctx.currentDraft.name}
              />
              <InlineIdentityConfirm
                confirmDisabled={Boolean(ctx.liveNameError)}
                disabled={ctx.identitySavingField !== null && ctx.identitySavingField !== "name"}
                fieldLabel={t("background.field.name")}
                loading={ctx.identitySavingField === "name"}
                onCancel={() => ctx.cancelIdentityField("name")}
                onConfirm={() => ctx.confirmIdentityField("name")}
                visible={ctx.nameDirty}
              />
            </div>
            {ctx.liveNameError ? <span className="field-error">{ctx.liveNameError}</span> : null}
          </span>
        </div>
        <div className="field-row">
          <label className="field-row__label" htmlFor="background-info-prefix-input">
            {t("background.field.spritePrefix")}
          </label>
          <span className="field-row__control">
            <div className="identity-field-group">
              <TextInput
                className={ctx.liveSpritePrefixError ? "input--error" : ""}
                id="background-info-prefix-input"
                onChange={(event) => ctx.updateField("sprite_prefix", event.target.value)}
                onKeyDown={(event) =>
                  handleIdentityKeyDown(event, {
                    canConfirm: !ctx.liveSpritePrefixError && ctx.identitySavingField === null,
                    disabled: ctx.identitySavingField !== null,
                    isDirty: ctx.spritePrefixDirty,
                    onCancel: () => ctx.cancelIdentityField("sprite_prefix"),
                    onConfirm: () => ctx.confirmIdentityField("sprite_prefix"),
                  })
                }
                value={ctx.currentDraft.sprite_prefix}
              />
              <InlineIdentityConfirm
                confirmDisabled={Boolean(ctx.liveSpritePrefixError)}
                disabled={ctx.identitySavingField !== null && ctx.identitySavingField !== "sprite_prefix"}
                fieldLabel={t("background.field.spritePrefix")}
                loading={ctx.identitySavingField === "sprite_prefix"}
                onCancel={() => ctx.cancelIdentityField("sprite_prefix")}
                onConfirm={() => ctx.confirmIdentityField("sprite_prefix")}
                visible={ctx.spritePrefixDirty}
              />
            </div>
            {ctx.liveSpritePrefixError ? <span className="field-error">{ctx.liveSpritePrefixError}</span> : null}
          </span>
        </div>
      </div>
    </section>
  );
}
