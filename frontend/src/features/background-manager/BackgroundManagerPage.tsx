import { useI18n } from "../../shared/i18n";
import { AlertDialog, EmptyState, PageSectionHost, QueryErrorState, useVisibleSectionNavItems } from "../../shared/ui";
import { BackgroundPageHeader } from "./BackgroundPageHeader";
import { BACKGROUND_MANAGER_SECTIONS } from "./backgroundSections";
import { backgroundDeleteDialogCopy } from "./backgroundUtils";
import { useBackgroundPageController } from "./controllers/useBackgroundPageController";
import "./BackgroundManagerPage.css";

export function BackgroundManagerPage() {
  const { t } = useI18n();
  const ctx = useBackgroundPageController();
  const navItems = useVisibleSectionNavItems(BACKGROUND_MANAGER_SECTIONS, ctx);
  const deleteCopy = ctx.pendingBackgroundDelete
    ? backgroundDeleteDialogCopy({ kind: "background", name: ctx.pendingBackgroundDelete }, t)
    : null;

  return (
    <div className="page background-page">
      <BackgroundPageHeader ctx={ctx} navItems={navItems} />

      {ctx.isLoading || ctx.isError || (!ctx.isLoading && !ctx.isError && !ctx.data.length) ? (
        <div className="background-page__status">
          {ctx.isLoading ? <EmptyState title={t("background.loading")} /> : null}
          {ctx.isError ? (
            <QueryErrorState
              error={ctx.queryError}
              onRetry={ctx.refetchBackgrounds}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {!ctx.isLoading && !ctx.isError && !ctx.data.length ? (
            <EmptyState body={t("background.emptyBody")} title={t("background.emptyTitle")} />
          ) : null}
        </div>
      ) : null}

      <section className="settings-grid background-page__content">
        <PageSectionHost ctx={ctx} sections={BACKGROUND_MANAGER_SECTIONS} />
      </section>

      <AlertDialog
        body={deleteCopy?.body ?? ""}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={deleteCopy?.confirmLabel ?? t("common.delete")}
        onCancel={ctx.cancelDeleteBackground}
        onConfirm={ctx.confirmDeleteBackground}
        open={Boolean(ctx.pendingBackgroundDelete)}
        title={deleteCopy?.title ?? t("common.delete")}
      />
    </div>
  );
}
