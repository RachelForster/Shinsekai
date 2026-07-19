import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Save } from "lucide-react";

import {
  getPluginUiDetail,
  pluginUiQueryKey,
  pluginsQueryKey,
  runPluginUiAction,
  savePluginUiConfig,
} from "../../entities/plugin/repository";
import type { PluginConfigAction, PluginManifest, PluginUIPage } from "../../entities/plugin/types";
import { useI18n } from "../../shared/i18n";
import {
  AlertDialog,
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
  localizePluginUiPage,
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
  const { language, t } = useI18n();
  const formGroups = useMemo(() => pluginConfigGroupsToFormGroups(page.schema ?? []), [page.schema]);
  const [draft, setDraft] = useState<PluginConfigDraft>(() => pluginConfigInitialValues(page));
  const [pendingAction, setPendingAction] = useState<PluginConfigAction | null>(null);

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
      const localizedPage = localizePluginUiPage(result.page, language);
      queryClient.invalidateQueries({ queryKey: pluginUiQueryKey(lookupId) });
      queryClient.invalidateQueries({ queryKey: pluginsQueryKey });
      showToast({
        kind: "success",
        message: localizedPage.restartHint || result.message,
        title: t("plugin.detail.saveSuccess"),
      });
    },
  });

  const actionMutation = useMutation({
    mutationFn: (action: PluginConfigAction) => runPluginUiAction(lookupId, page.id, action.id, draft),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("plugin.detail.saveFailed"),
        title: t("plugin.toast.operationFailed"),
      });
    },
    onSuccess(result) {
      setDraft(pluginConfigInitialValues(result.page));
      const localizedPage = localizePluginUiPage(result.page, language);
      queryClient.invalidateQueries({ queryKey: pluginUiQueryKey(lookupId) });
      queryClient.invalidateQueries({ queryKey: pluginsQueryKey });
      showToast({
        kind: "success",
        message: localizedPage.restartHint || result.message,
        title: result.message,
      });
    },
  });

  const handleActionClick = (action: PluginConfigAction) => {
    if (action.confirm) {
      setPendingAction(action);
    } else {
      actionMutation.mutate(action);
    }
  };

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

  const actions = (page.actions ?? []).filter((a) => a.id);

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
        {actions.map((action) => (
          <AsyncButton
            key={action.id}
            loading={actionMutation.isPending && actionMutation.variables?.id === action.id}
            onClick={() => handleActionClick(action)}
            tooltip={action.description || undefined}
            variant={action.variant}
          >
            {action.label}
          </AsyncButton>
        ))}
      </div>
      {pendingAction ? (
        <AlertDialog
          body={pendingAction.confirm ?? ""}
          cancelLabel={t("common.cancel")}
          confirmLabel={t("common.confirm")}
          onCancel={() => setPendingAction(null)}
          onConfirm={() => {
            actionMutation.mutate(pendingAction);
            setPendingAction(null);
          }}
          open
          title={pendingAction.label}
        />
      ) : null}
    </div>
  );
}

function PluginPagePanel({ lookupId, page }: { lookupId: string; page: PluginUIPage }) {
  if (page.frontendUrl) {
    const frontendFrameSrc = resolvePluginFrontendFrameSrc(page.frontendUrl);
    return (
      <section className="section plugin-frontend-frame-section">
        <iframe
          className="plugin-frontend-frame"
          sandbox="allow-forms allow-same-origin allow-scripts"
          src={frontendFrameSrc}
          title={page.title}
        />
      </section>
    );
  }
  return <PluginConfigPanel key={pluginConfigPageStateKey(page)} lookupId={lookupId} page={page} />;
}

export function resolvePluginFrontendFrameSrc(frontendUrl: string) {
  if (!frontendUrl.startsWith("/api/") || typeof window === "undefined") {
    return frontendUrl;
  }
  const bridgeBase = new URLSearchParams(window.location.search).get("shinsekai_bridge")?.trim();
  if (!bridgeBase) {
    return frontendUrl;
  }
  try {
    return new URL(frontendUrl, bridgeBase).toString();
  } catch {
    return frontendUrl;
  }
}

function pluginConfigPageStateKey(page: PluginUIPage) {
  return `${pluginUiPageKey(page)}:${page.schema?.length ?? 0}:${JSON.stringify(page.values ?? {})}`;
}

/* ── Detail page ── */

interface PluginDetailPanelProps {
  detailPlugin: PluginManifest;
  initialPageId?: string;
  onBack: () => void;
}

export function PluginDetailPanel({ detailPlugin, initialPageId = "", onBack }: PluginDetailPanelProps) {
  const { language, t } = useI18n();
  const detailLookupId = pluginActionId(detailPlugin);
  const [activeDetailPageId, setActiveDetailPageId] = useState("");

  const pluginDetailQuery = useQuery({
    enabled: Boolean(detailLookupId),
    queryFn: () => getPluginUiDetail(detailLookupId),
    queryKey: pluginUiQueryKey(detailLookupId),
  });

  const fallbackDetailPages = useMemo(() => fallbackPluginUiPages(detailPlugin), [detailPlugin]);
  const rawDetailPages = pluginDetailQuery.data?.pages ?? fallbackDetailPages;
  const detailPages = useMemo(
    () => rawDetailPages.map((page) => localizePluginUiPage(page, language)),
    [language, rawDetailPages],
  );
  const detailPluginRow = pluginDetailQuery.data?.plugin ?? detailPlugin;
  const detailPageSignature = detailPages.map(pluginUiPageKey).join("|");

  useEffect(() => {
    const pageKeys = detailPages.map(pluginUiPageKey);
    if (pageKeys.length && !pageKeys.includes(activeDetailPageId)) {
      const preferredPage = detailPages.find(
        (page) => page.id === initialPageId || pluginUiPageKey(page) === initialPageId,
      );
      setActiveDetailPageId(preferredPage ? pluginUiPageKey(preferredPage) : pageKeys[0]);
    }
  }, [activeDetailPageId, detailPageSignature, detailPages, initialPageId]);

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
