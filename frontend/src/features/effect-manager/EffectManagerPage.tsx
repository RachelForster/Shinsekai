import { useMemo } from "react";

import { useI18n } from "../../shared/i18n";
import { usePluginPageSectionDescriptors } from "../../shared/plugin/PluginPageSections";
import { AlertDialog, PageSectionHost, useVisibleSectionNavItems } from "../../shared/ui";
import { EffectPageHeader } from "./EffectPageHeader";
import type { EffectPageContext } from "./effectContext";
import { EFFECT_MANAGER_SECTIONS } from "./effectSections";
import { useEffectPageController } from "./controllers/useEffectPageController";
import "./EffectManagerPage.css";

export function EffectManagerPage() {
  const { t } = useI18n();
  const ctx = useEffectPageController();
  const entityId = ctx.isCreating ? undefined : ctx.selectedName || undefined;
  const pluginSections = usePluginPageSectionDescriptors<EffectPageContext>(
    { entityId, entityType: "effect", page: "effect" },
    { context: { entityId, entityType: "effect", page: "effect" }, defaultSlot: "body", orderBase: 1000 },
  );
  const allSections = useMemo(() => [...EFFECT_MANAGER_SECTIONS, ...pluginSections], [pluginSections]);
  const navItems = useVisibleSectionNavItems(allSections, ctx);

  return (
    <div className="page effect-page">
      <EffectPageHeader ctx={ctx} navItems={navItems} />

      <section className="settings-grid effect-page__content">
        <PageSectionHost ctx={ctx} sections={allSections} />
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
