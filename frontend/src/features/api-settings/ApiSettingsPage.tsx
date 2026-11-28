import { useMemo } from "react";
import { RotateCcw, Save } from "lucide-react";

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
import { ChatInitializationDialog } from "../chat-startup/ChatInitializationDialog";
import { API_SETTINGS_SECTIONS } from "./apiSections";
import type { ApiSettingsPageContext } from "./apiSettingsContext";
import { useApiSettingsPageController } from "./controllers/useApiSettingsPageController";
import "./ApiSettingsPage.css";

interface ApiSettingsReadyViewProps {
  ctx: ApiSettingsPageContext;
  initialization: ReturnType<typeof useApiSettingsPageController>["initialization"];
}

function ApiSettingsReadyView({ ctx, initialization }: ApiSettingsReadyViewProps) {
  const { t } = useI18n();
  const pluginSections = usePluginPageSectionDescriptors<ApiSettingsPageContext>(
    { page: "api" },
    { context: { page: "api" }, defaultSlot: "body", orderBase: 1000 },
  );
  const allSections = useMemo(() => [...API_SETTINGS_SECTIONS, ...pluginSections], [pluginSections]);
  const navItems = useVisibleSectionNavItems(allSections, ctx);

  return (
    <div className="page api-page">
      <header className="page__header api-page__header">
        <div>
          <h1 className="page__title">{t("api.title")}</h1>
        </div>
        <div className="page__actions">
          <PluginSlot context={{ page: "api" }} maxInline={2} slot="api-header-actions" />
          <AsyncButton
            disabled={ctx.resumeDisabled}
            icon={<RotateCcw aria-hidden className="button__icon" />}
            loading={ctx.resumePending}
            onClick={ctx.handleResume}
            tooltip={t("api.resume.tip")}
          >
            {t("api.resume.btn")}
          </AsyncButton>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={ctx.savePending}
            onClick={ctx.handleSave}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
        </div>
        <PageSectionNav ariaLabel={t("api.title")} items={navItems} />
      </header>

      <PageSectionHost ctx={ctx} sections={allSections} />

      <ChatInitializationDialog
        error={initialization.initializationError}
        onClose={initialization.closeInitialization}
        open={initialization.initializationOpen}
        pending={initialization.initializationPending}
        task={initialization.initializationTask}
      />
    </div>
  );
}

export function ApiSettingsPage() {
  const { t } = useI18n();
  const { ctx, initialization, isError, queryError, refetchConfig } = useApiSettingsPageController();

  if (isError) {
    return (
      <QueryErrorState
        body={t("api.error.saveFallback")}
        error={queryError}
        onRetry={refetchConfig}
        retryLabel={t("common.retry")}
        title={t("common.operationFailed")}
      />
    );
  }

  if (!ctx) {
    return <EmptyState title={t("api.loading")} />;
  }

  return <ApiSettingsReadyView ctx={ctx} initialization={initialization} />;
}
