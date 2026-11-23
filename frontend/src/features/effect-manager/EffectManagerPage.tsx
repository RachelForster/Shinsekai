import { useI18n } from "../../shared/i18n";
import { AlertDialog, PageSectionHost, useVisibleSectionNavItems } from "../../shared/ui";
import { EffectPageHeader } from "./EffectPageHeader";
import { EFFECT_MANAGER_SECTIONS } from "./effectSections";
import { useEffectPageController } from "./controllers/useEffectPageController";
import "./EffectManagerPage.css";

export function EffectManagerPage() {
  const { t } = useI18n();
  const ctx = useEffectPageController();
  const navItems = useVisibleSectionNavItems(EFFECT_MANAGER_SECTIONS, ctx);

  return (
    <div className="page effect-page">
      <EffectPageHeader ctx={ctx} navItems={navItems} />

      <section className="settings-grid effect-page__content">
        <PageSectionHost ctx={ctx} sections={EFFECT_MANAGER_SECTIONS} />
      </section>

      <AlertDialog
        body={t("effect.delete.confirmBody", { name: ctx.pendingEffectDelete ?? "" })}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("common.delete")}
        onCancel={ctx.cancelDeleteEffect}
        onConfirm={ctx.confirmDeleteEffect}
        open={Boolean(ctx.pendingEffectDelete)}
        title={t("effect.delete.confirmTitle")}
      />
    </div>
  );
}
