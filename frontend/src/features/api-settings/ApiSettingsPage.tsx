import { RotateCcw, Save } from "lucide-react";

import { useI18n } from "../../shared/i18n";
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
  const navItems = useVisibleSectionNavItems(API_SETTINGS_SECTIONS, ctx);

  return (
    <div className="page api-page">
      <header className="page__header api-page__header">
        <div>
          <h1 className="page__title">{t("api.title")}</h1>
        </div>
        <div className="page__actions">
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

      <PageSectionHost ctx={ctx} sections={API_SETTINGS_SECTIONS} />

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
