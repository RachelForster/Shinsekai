import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Save } from "lucide-react";

import {
  getPluginUiDetail,
  pluginUiQueryKey,
  pluginsQueryKey,
  savePluginUiConfig,
} from "../../entities/plugin/repository";
import type { PluginManifest, PluginUIPage } from "../../entities/plugin/types";
import { useI18n } from "../../shared/i18n";
import {
  AsyncButton,
  Button,
  EmptyState,
  QueryErrorState,
  SchemaDrivenForm,
  SegmentedTabs,
  useToast,
} from "../../shared/ui";
import {
  fallbackPluginUiPages,
  pluginActionId,
  pluginConfigInitialValues,
  pluginConfigGroupsToFormGroups,
  pluginUiPageKey,
  type PluginConfigDraft,
} from "./pluginUtils";

/* ── Config form for a single plugin UI page ── */

function PluginConfigPanel({ lookupId, page }: { lookupId: string; page: PluginUIPage }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const formGroups = useMemo(() => pluginConfigGroupsToFormGroups(page.schema ?? []), [page.schema]);
  const [draft, setDraft] = useState<PluginConfigDraft>(() => pluginConfigInitialValues(page));

  useEffect(() => {
    setDraft(pluginConfigInitialValues(page));
  }, [page]);

  const saveMutation = useMutation({
    mutationFn: () => savePluginUiConfig(lookupId, page.id, draft),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("plugin.detail.saveFailed"),
        title: t("plugin.toast.operationFailed"),
      });
    },
    onSuccess(result) {
      setDraft(pluginConfigInitialValues(result.page));
      queryClient.invalidateQueries({ queryKey: pluginUiQueryKey(lookupId) });
      queryClient.invalidateQueries({ queryKey: pluginsQueryKey });
      showToast({
        kind: "success",
        message: result.page.restartHint || result.message,
        title: t("plugin.detail.saveSuccess"),
      });
    },
  });

  if (!page.schema?.length) {
    return (
      <section className="section plugin-detail-page__notice">
        <div className="section__header">
          <h2 className="section__title">{page.title}</h2>
          <span className="inline-status">
            {page.kind === "tools" ? t("plugin.detail.kindTools") : t("plugin.detail.kindSettings")}
          </span>
        </div>
        <p className="plugin-card__description">{page.unavailableReason || t("plugin.detail.pyqtNotice")}</p>
      </section>
    );
  }

  return (
    <div className="plugin-config-panel">
      {page.description ? <p className="section__description">{page.description}</p> : null}
      <SchemaDrivenForm groups={formGroups} onChange={setDraft} value={draft} />
      {page.restartHint ? <p className="inline-status">{page.restartHint}</p> : null}
      <div className="plugin-detail-page__footer">
        <AsyncButton
          icon={<Save aria-hidden className="button__icon" />}
          loading={saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
          variant="primary"
        >
          {t("plugin.detail.save")}
        </AsyncButton>
      </div>
    </div>
  );
}

function PluginPagePanel({ lookupId, page }: { lookupId: string; page: PluginUIPage }) {
  if (page.frontendUrl) {
    return (
      <section className="section plugin-frontend-frame-section">
        <iframe
          className="plugin-frontend-frame"
          sandbox="allow-forms allow-same-origin allow-scripts"
          src={page.frontendUrl}
          title={page.title}
        />
      </section>
    );
  }
  return <PluginConfigPanel lookupId={lookupId} page={page} />;
}

/* ── Detail page ── */

interface PluginDetailPanelProps {
  detailPlugin: PluginManifest;
  onBack: () => void;
}

export function PluginDetailPanel({ detailPlugin, onBack }: PluginDetailPanelProps) {
  const { t } = useI18n();
  const detailLookupId = pluginActionId(detailPlugin);
  const [activeDetailPageId, setActiveDetailPageId] = useState("");

  const pluginDetailQuery = useQuery({
    enabled: Boolean(detailLookupId),
    queryFn: () => getPluginUiDetail(detailLookupId),
    queryKey: pluginUiQueryKey(detailLookupId),
  });

  const fallbackDetailPages = useMemo(() => fallbackPluginUiPages(detailPlugin), [detailPlugin]);
  const detailPages = pluginDetailQuery.data?.pages ?? fallbackDetailPages;
  const detailPluginRow = pluginDetailQuery.data?.plugin ?? detailPlugin;
  const detailPageSignature = detailPages.map(pluginUiPageKey).join("|");

  useEffect(() => {
    const pageKeys = detailPages.map(pluginUiPageKey);
    if (pageKeys.length && !pageKeys.includes(activeDetailPageId)) {
      setActiveDetailPageId(pageKeys[0]);
    }
  }, [activeDetailPageId, detailPageSignature, detailPages]);

  const activeDetailPage = detailPages.find((page) => pluginUiPageKey(page) === activeDetailPageId) ?? detailPages[0];
  const loaded = detailPluginRow.loaded !== false;
  const statusLabel = !detailPluginRow.enabled
    ? t("plugin.status.disabled")
    : loaded
      ? t("plugin.status.enabled")
      : t("plugin.status.unavailable");

  return (
    <div className="page plugin-detail-page">
      <header className="page__header">
        <div>
          <Button
            className="plugin-detail-page__back"
            icon={<ArrowLeft aria-hidden className="button__icon" />}
            onClick={onBack}
            variant="ghost"
          >
            {t("plugin.detail.back")}
          </Button>
          <h1 className="page__title">{t("plugin.detail.title", { title: detailPluginRow.title })}</h1>
          <p className="page__description">
            {t("plugin.version")}: {detailPluginRow.version || "-"}
            {detailPluginRow.author ? ` · ${t("plugin.author")}: ${detailPluginRow.author}` : ""}
          </p>
        </div>
        <span className="plugin-card__status" data-enabled={detailPluginRow.enabled && loaded} data-loaded={loaded}>
          {statusLabel}
        </span>
      </header>

      {!loaded && detailPluginRow.enabled ? (
        <section className="section">
          <p className="plugin-card__description">{detailPluginRow.loadError || t("plugin.loadError.unavailable")}</p>
        </section>
      ) : null}

      {pluginDetailQuery.isLoading && !pluginDetailQuery.data ? (
        <EmptyState title={t("plugin.detail.loading")} />
      ) : null}
      {pluginDetailQuery.isError ? (
        <QueryErrorState
          body={t("plugin.detail.errorBody")}
          error={pluginDetailQuery.error}
          onRetry={() => void pluginDetailQuery.refetch()}
          retryLabel={t("common.retry")}
          title={t("plugin.detail.errorTitle")}
        />
      ) : null}
      {!pluginDetailQuery.isLoading && !detailPages.length ? (
        <EmptyState title={t("plugin.detail.noUi")} body={t("plugin.detail.pyqtNotice")} />
      ) : null}
      {detailPages.length ? (
        <>
          <SegmentedTabs
            ariaLabel={t("plugin.detail.pages")}
            items={detailPages.map((page) => ({ id: pluginUiPageKey(page), label: page.title }))}
            onChange={setActiveDetailPageId}
            value={activeDetailPage ? pluginUiPageKey(activeDetailPage) : activeDetailPageId}
          />
          {activeDetailPage ? <PluginPagePanel lookupId={detailLookupId} page={activeDetailPage} /> : null}
        </>
      ) : null}
    </div>
  );
}
