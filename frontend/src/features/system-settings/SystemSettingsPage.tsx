import { useMemo } from "react";
import { Save } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { usePluginPageSectionDescriptors } from "../../shared/plugin/PluginPageSections";
import { PluginSlot } from "../../shared/plugin/PluginSlot";
import {
  AsyncButton,
  EmptyState,
  PageSectionHost,
  PageSectionNav,
  QueryErrorState,
  useVisibleSectionNavItems,
} from "../../shared/ui";
import { RuntimeModeDialog } from "../runtime-mode/RuntimeModeDialog";
import { useSystemSettingsController } from "./controllers/useSystemSettingsController";
import { SYSTEM_SETTINGS_SECTIONS } from "./systemSections";
import type { SystemSettingsPageContext } from "./systemSettingsContext";
// Shared page layout classes (.page, .section, .form-grid, .field-row) come from shared/theme/settings-base.css
import "./SystemSettingsPage.css";

function SystemSettingsReadyView({
  closeRuntimeModeDialog,
  ctx,
  handleSave,
  runtimeModeOpen,
}: {
  closeRuntimeModeDialog: () => void;
  ctx: SystemSettingsPageContext;
  handleSave: () => void;
  runtimeModeOpen: boolean;
}) {
  const { t } = useI18n();
  const pluginSections = usePluginPageSectionDescriptors<SystemSettingsPageContext>(
    { page: "system" },
    { context: { page: "system" }, defaultSlot: "body", orderBase: 1000 },
  );
  const allSections = useMemo(() => [...SYSTEM_SETTINGS_SECTIONS, ...pluginSections], [pluginSections]);
  const navItems = useVisibleSectionNavItems(allSections, ctx);

  return (
    <div className="page system-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("system.title")}</h1>
        </div>
        <div className="page__actions">
          <PluginSlot context={{ page: "system" }} maxInline={2} slot="system-header-actions" />
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={ctx.savePending}
            onClick={handleSave}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
        </div>
        <PageSectionNav ariaLabel={t("system.title")} items={navItems} />
      </header>

      <PageSectionHost ctx={ctx} sections={allSections} />
      <RuntimeModeDialog onClose={closeRuntimeModeDialog} open={runtimeModeOpen} />
    </div>
  );
}

export function SystemSettingsPage() {
  const { t } = useI18n();
  const { closeRuntimeModeDialog, configQuery, ctx, handleSave, isLoading, runtimeModeOpen } =
    useSystemSettingsController();

  if (configQuery.isError) {
    return (
      <QueryErrorState
        body={t("system.error.saveFallback")}
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
        retryLabel={t("common.retry")}
        title={t("common.operationFailed")}
      />
    );
  }

  if (isLoading || !ctx) {
    return <EmptyState title={t("system.loading")} />;
  }

  return (
    <SystemSettingsReadyView
      closeRuntimeModeDialog={closeRuntimeModeDialog}
      ctx={ctx}
      handleSave={handleSave}
      runtimeModeOpen={runtimeModeOpen}
    />
  );
}
