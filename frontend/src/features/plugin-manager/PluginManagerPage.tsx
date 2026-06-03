import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Power, RotateCcw, Settings, Trash2 } from "lucide-react";

import {
  installPlugin,
  listPluginCatalog,
  listPlugins,
  pluginCatalogQueryKey,
  pluginsQueryKey,
  runAppUpdate,
  setPluginEnabled,
  uninstallPlugin,
} from "../../entities/plugin/repository";
import type {
  AppUpdateRefKind,
  AppUpdateResult,
  PluginInstallInput,
  PluginManifest,
} from "../../entities/plugin/types";
import {
  desktopRestartErrorMessage,
  isTauriDesktop,
  restartDesktopBridge,
  writeDesktopRestartDebugLog,
} from "../../shared/desktop/desktopApi";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
  QueryErrorState,
  SegmentedTabs,
  useToast,
} from "../../shared/ui";
import { McpSettingsPanel } from "./McpSettingsPanel";
import { PluginCatalogPanel } from "./PluginCatalogPanel";
import { PluginDetailPanel } from "./PluginDetailPanel";
import { PluginListControls, searchablePluginText, usePagedPluginList } from "./PluginListControls";
import {
  pluginActionId,
  pluginHasManifestEntry,
  pluginInstallSource,
  pluginSettingsPages,
  pluginToolsTabs,
  type PluginView,
} from "./pluginUtils";
import "./PluginManagerPage.css";

const INSTALLED_PLUGIN_PAGE_SIZE = 8;

export function PluginManagerPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const pluginsQuery = useQuery({ queryFn: listPlugins, queryKey: pluginsQueryKey });
  const data = pluginsQuery.data ?? [];
  const isLoading = pluginsQuery.isLoading;
  const [view, setView] = useState<PluginView>("installed");
  const [installingSource, setInstallingSource] = useState("");
  const [installTask, setInstallTask] = useState<TaskSnapshot<PluginManifest> | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<PluginManifest | null>(null);
  const [detailPlugin, setDetailPlugin] = useState<PluginManifest | null>(null);
  const [pluginReloadPending, setPluginReloadPending] = useState(false);
  const [appUpdateTask, setAppUpdateTask] = useState<TaskSnapshot<AppUpdateResult> | null>(null);
  const installedPluginMatches = useCallback((plugin: PluginManifest, query: string) => {
    return searchablePluginText([
      plugin.title,
      plugin.id,
      plugin.entry,
      plugin.description,
      plugin.author,
      plugin.version,
      plugin.directory,
      plugin.enabled ? "enabled" : "disabled",
      plugin.loaded === false ? "unavailable not loaded" : "loaded",
    ]).includes(query);
  }, []);
  const installedPlugins = usePagedPluginList({
    items: data,
    matcher: installedPluginMatches,
    pageSize: INSTALLED_PLUGIN_PAGE_SIZE,
  });

  const catalogQuery = useQuery({
    enabled: view === "discover",
    queryFn: listPluginCatalog,
    queryKey: pluginCatalogQueryKey,
    retry: 1,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ enabled, id }: { enabled: boolean; id: string }) => setPluginEnabled(id, enabled),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("plugin.error.toggleFallback"),
        title: t("plugin.toast.operationFailed"),
      });
    },
    onSuccess(plugin) {
      queryClient.invalidateQueries({ queryKey: pluginsQueryKey });
      showToast({
        kind: "success",
        message: t("plugin.toast.restartHint"),
        title: plugin.enabled ? t("plugin.toast.enabled") : t("plugin.toast.disabled"),
      });
    },
  });

  const installMutation = useMutation({
    mutationFn: (input: PluginInstallInput | string) => installPlugin(input, { onTaskUpdate: setInstallTask }),
    onMutate(input) {
      setInstallTask(null);
      setInstallingSource(pluginInstallSource(input));
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("plugin.error.installFallback"),
        title: t("plugin.toast.installFailed"),
      });
    },
    onSuccess(plugin) {
      queryClient.invalidateQueries({ queryKey: pluginsQueryKey });
      queryClient.invalidateQueries({ queryKey: pluginCatalogQueryKey });
      showToast({
        kind: "success",
        message: `${plugin.title}。${t("plugin.toast.restartHint")}`,
        title: t("plugin.toast.installSuccess"),
      });
    },
    onSettled() {
      setInstallingSource("");
    },
  });

  const uninstallMutation = useMutation({
    mutationFn: (id: string) => uninstallPlugin(id),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("plugin.error.uninstallFallback"),
        title: t("plugin.toast.operationFailed"),
      });
    },
    onSuccess(result) {
      queryClient.invalidateQueries({ queryKey: pluginsQueryKey });
      queryClient.invalidateQueries({ queryKey: pluginCatalogQueryKey });
      setPendingUninstall(null);
      showToast({
        kind: "success",
        message: result.folderNote || `${result.message} ${t("plugin.toast.restartHint")}`,
        title: t("plugin.toast.uninstalled"),
      });
    },
  });

  const appUpdateMutation = useMutation({
    mutationFn: (opts: { refKind: AppUpdateRefKind; tagName: string }) =>
      runAppUpdate(
        { refKind: opts.refKind, tagName: opts.refKind === "tag" ? opts.tagName : undefined },
        { onTaskUpdate: setAppUpdateTask },
      ),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("plugin.appUpdate.failed"),
        title: t("plugin.appUpdate.title"),
      });
    },
    onMutate() {
      setAppUpdateTask(null);
    },
    onSuccess(result) {
      queryClient.invalidateQueries({ queryKey: ["plugins", "app-update", "info"] });
      showToast({ kind: "success", message: result.message, title: t("plugin.appUpdate.success") });
    },
  });

  const pluginBusy = toggleMutation.isPending || uninstallMutation.isPending;
  const desktopApp = isTauriDesktop();

  const handleReloadPlugins = async () => {
    setPluginReloadPending(true);
    try {
      await waitForReloadAnimationFrame();
      const runtime = await restartDesktopBridge();
      await waitForPluginBridgeReady(runtime.bridgeUrl);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: pluginsQueryKey }),
        queryClient.invalidateQueries({ queryKey: pluginCatalogQueryKey }),
        queryClient.invalidateQueries({ queryKey: ["plugins", "app-update", "info"] }),
      ]);
      showToast({
        kind: "success",
        title: t("plugin.appRestart.success"),
      });
    } catch (error) {
      await writeDesktopRestartDebugLog(`PluginManagerPage plugin reload catch: ${desktopRestartErrorMessage(error)}`);
      showToast({
        kind: "error",
        message: desktopRestartErrorMessage(error) || t("plugin.appRestart.failed"),
        title: t("plugin.appRestart.button"),
      });
    } finally {
      setPluginReloadPending(false);
    }
  };

  if (detailPlugin) {
    return <PluginDetailPanel detailPlugin={detailPlugin} onBack={() => setDetailPlugin(null)} />;
  }

  return (
    <div className="page plugin-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("nav.plugins")}</h1>
          <p className="page__description">{t("plugin.description")}</p>
          {pluginReloadPending ? (
            <span className="inline-status plugin-reload-status">{t("plugin.appRestart.pending")}</span>
          ) : null}
        </div>
        <div className="page__actions plugin-page__actions">
          {desktopApp ? (
            <AsyncButton
              className={
                pluginReloadPending ? "plugin-reload-button plugin-reload-button--active" : "plugin-reload-button"
              }
              disabled={pluginReloadPending}
              icon={
                <RotateCcw
                  aria-hidden
                  className={
                    pluginReloadPending
                      ? "button__icon plugin-reload-button__icon plugin-reload-button__icon--spinning"
                      : "button__icon plugin-reload-button__icon"
                  }
                />
              }
              onClick={() => void handleReloadPlugins()}
              variant="ghost"
            >
              {t("plugin.appRestart.button")}
            </AsyncButton>
          ) : null}
          <SegmentedTabs
            ariaLabel={t("common.subpages")}
            className="plugin-page__tabs"
            items={[
              { id: "installed", label: t("plugin.installed.title") },
              { id: "discover", label: t("plugin.catalog.title") },
              { id: "mcp", label: "MCP" },
            ]}
            onChange={setView}
            value={view}
          />
        </div>
      </header>

      {view === "discover" ? (
        <PluginCatalogPanel
          appUpdateMutation={appUpdateMutation}
          appUpdateTask={appUpdateTask}
          catalogQuery={catalogQuery}
          installMutation={installMutation}
          installTask={installTask}
          installingSource={installingSource}
        />
      ) : view === "mcp" ? (
        <McpSettingsPanel />
      ) : (
        <section className="section">
          <div className="section__header">
            <h2 className="section__title">{t("plugin.installed.title")}</h2>
            <span className="inline-status">
              {toggleMutation.isPending
                ? t("plugin.status.updating")
                : t("plugin.installed.count", { count: data.length })}
            </span>
          </div>
          {isLoading ? <EmptyState title={t("plugin.installed.loading")} /> : null}
          {pluginsQuery.isError ? (
            <QueryErrorState
              error={pluginsQuery.error}
              onRetry={() => void pluginsQuery.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {!isLoading && !pluginsQuery.isError && data.length ? (
            <PluginListControls
              filteredCount={installedPlugins.filteredItems.length}
              page={installedPlugins.page}
              placeholder={t("plugin.list.searchInstalled")}
              query={installedPlugins.query}
              setPage={installedPlugins.setPage}
              setQuery={installedPlugins.setQuery}
              totalCount={installedPlugins.totalItems}
              totalPages={installedPlugins.totalPages}
            />
          ) : null}
          {!isLoading && !pluginsQuery.isError && installedPlugins.pagedItems.length ? (
            <div className="plugin-card-grid">
              {installedPlugins.pagedItems.map((plugin) => {
                const loaded = plugin.loaded !== false;
                const statusLabel = !plugin.enabled
                  ? t("plugin.status.disabled")
                  : loaded
                    ? t("plugin.status.enabled")
                    : t("plugin.status.unavailable");
                return (
                  <article className="plugin-card" key={plugin.id}>
                    <div className="plugin-card__title-row">
                      <div className="plugin-card__title">
                        <strong>{plugin.title}</strong>
                        {plugin.title !== plugin.id ? (
                          <span className="inline-status">
                            {t("plugin.id")}: {plugin.id}
                          </span>
                        ) : null}
                      </div>
                      <span
                        className="plugin-card__status"
                        data-enabled={plugin.enabled && loaded}
                        data-loaded={loaded}
                      >
                        {statusLabel}
                      </span>
                    </div>
                    {!loaded && plugin.enabled ? (
                      <p className="plugin-card__description">
                        {plugin.loadError || t("plugin.loadError.unavailable")}
                      </p>
                    ) : plugin.description ? (
                      <p className="plugin-card__description">{plugin.description}</p>
                    ) : null}
                    <div className="plugin-card__meta">
                      <span>
                        {t("plugin.version")}: {plugin.version || "-"}
                      </span>
                      {plugin.author ? (
                        <span>
                          {t("plugin.author")}: {plugin.author}
                        </span>
                      ) : null}
                      {plugin.directory ? (
                        <span>
                          {t("plugin.directory")}: {plugin.directory}
                        </span>
                      ) : null}
                    </div>
                    <div className="plugin-card__actions">
                      <Button
                        disabled={pluginBusy || !pluginHasManifestEntry(plugin)}
                        icon={<Trash2 aria-hidden className="button__icon" />}
                        onClick={() => setPendingUninstall(plugin)}
                        variant="danger"
                      >
                        {t("plugin.action.uninstall")}
                      </Button>
                      <Button
                        disabled={pluginBusy || !pluginHasManifestEntry(plugin)}
                        icon={<Power aria-hidden className="button__icon" />}
                        onClick={() => toggleMutation.mutate({ enabled: !plugin.enabled, id: pluginActionId(plugin) })}
                        variant={plugin.enabled ? "default" : "ghost"}
                      >
                        {plugin.enabled ? t("plugin.toggle.disable") : t("plugin.toggle.enable")}
                      </Button>
                      {pluginSettingsPages(plugin).length || pluginToolsTabs(plugin).length ? (
                        <Button
                          disabled={pluginBusy || !loaded}
                          icon={<Settings aria-hidden className="button__icon" />}
                          onClick={() => setDetailPlugin(plugin)}
                          variant="ghost"
                        >
                          {t("plugin.action.viewConfig")}
                        </Button>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
          ) : null}
          {!isLoading && !pluginsQuery.isError && data.length && !installedPlugins.filteredItems.length ? (
            <EmptyState title={t("plugin.list.noMatches")} />
          ) : null}
          {!isLoading && !pluginsQuery.isError && !data.length ? (
            <EmptyState title={t("plugin.installed.emptyTitle")} body={t("plugin.installed.emptyBody")} />
          ) : null}
        </section>
      )}

      <AlertDialog
        body={t("plugin.uninstall.confirmBody", { title: pendingUninstall?.title ?? "" })}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("plugin.action.uninstall")}
        onCancel={() => setPendingUninstall(null)}
        onConfirm={() => pendingUninstall && uninstallMutation.mutate(pluginActionId(pendingUninstall))}
        open={Boolean(pendingUninstall)}
        title={t("plugin.uninstall.confirmTitle")}
      />
    </div>
  );
}

function waitForReloadAnimationFrame() {
  if (typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => resolve());
    });
  });
}

async function waitForPluginBridgeReady(bridgeUrl: string, timeoutMs = 15000) {
  if (!bridgeUrl) {
    return;
  }
  const url = `${bridgeUrl.replace(/\/$/, "")}/api/health`;
  const started = Date.now();
  let lastError: unknown;

  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      const payload = await response.json().catch(() => null);
      if (response.ok && payload?.ok === true) {
        return;
      }
    } catch (error) {
      lastError = error;
    }
    await delayPluginReload(160);
  }

  throw new Error(lastError instanceof Error ? lastError.message : `Timed out waiting for plugin service at ${url}`);
}

function delayPluginReload(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
