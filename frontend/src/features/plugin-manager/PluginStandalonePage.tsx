import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import { getPluginUiDetail, pluginUiQueryKey } from "../../entities/plugin/repository";
import { useI18n } from "../../shared/i18n";
import { PluginIframeHost } from "../../shared/plugin/PluginIframeHost";
import { localizePluginUiPage } from "../../shared/plugin/pluginI18n";
import { Button, EmptyState, QueryErrorState } from "../../shared/ui";
import "./PluginStandalonePage.css";

export function PluginStandalonePage() {
  const { pageId = "", pluginId = "" } = useParams<{ pageId?: string; pluginId?: string }>();
  const navigate = useNavigate();
  const { language, t } = useI18n();
  const decodedPluginId = decodeURIComponent(pluginId);
  const decodedPageId = decodeURIComponent(pageId);

  const detailQuery = useQuery({
    enabled: Boolean(decodedPluginId),
    queryFn: () => getPluginUiDetail(decodedPluginId),
    queryKey: pluginUiQueryKey(decodedPluginId),
  });

  const localizedPage = useMemo(() => {
    const pages = detailQuery.data?.pages ?? [];
    const match = pages.find((item) => item.id === decodedPageId);
    return match ? localizePluginUiPage(match, language) : undefined;
  }, [decodedPageId, detailQuery.data?.pages, language]);

  const backButton = (
    <Button
      icon={<ArrowLeft aria-hidden className="button__icon" />}
      onClick={() => navigate("/settings/plugins")}
      variant="ghost"
    >
      {t("plugin.page.backToPlugins")}
    </Button>
  );

  if (detailQuery.isLoading && !detailQuery.data) {
    return (
      <div className="page plugin-standalone-page">
        <EmptyState title={t("plugin.detail.loading")} />
      </div>
    );
  }

  if (detailQuery.isError) {
    return (
      <div className="page plugin-standalone-page">
        <QueryErrorState
          body={t("plugin.detail.errorBody")}
          error={detailQuery.error}
          onRetry={() => void detailQuery.refetch()}
          retryLabel={t("common.retry")}
          title={t("plugin.detail.errorTitle")}
        />
      </div>
    );
  }

  if (!localizedPage || !localizedPage.frontendUrl) {
    return (
      <div className="page plugin-standalone-page">
        <header className="page__header">
          <div>{backButton}</div>
        </header>
        <EmptyState
          action={backButton}
          body={localizedPage?.unavailableReason || undefined}
          title={localizedPage?.title || t("plugin.page.notFound")}
        />
      </div>
    );
  }

  const pluginTitle = detailQuery.data?.plugin.title || decodedPluginId;

  return (
    <div className="page plugin-standalone-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{localizedPage.navLabel || localizedPage.title}</h1>
          <p className="page__subtitle">{localizedPage.description || pluginTitle}</p>
        </div>
        <div className="page__actions">{backButton}</div>
      </header>
      <section className="section plugin-standalone-page__frame-section">
        <PluginIframeHost
          className="plugin-standalone-page__frame"
          context={{ page: `plugins/${decodedPluginId}/${decodedPageId}` }}
          frontendUrl={localizedPage.frontendUrl}
          pluginId={decodedPluginId}
          surface="page"
          title={localizedPage.title}
        />
      </section>
    </div>
  );
}
