import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpCircle, BookOpen, Power, RotateCcw, Send, Settings, Trash2 } from "lucide-react";

import { openExternal } from "../../entities/files/repository";
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
  PluginCatalogItem,
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
  TaskProgress,
  useToast,
} from "../../shared/ui";
import defaultPluginLogoUrl from "../../assets/default-plugin-logo.svg";
import { McpSettingsPanel } from "./McpSettingsPanel";
import { PluginCatalogInstallDialog, PluginCatalogPanel } from "./PluginCatalogPanel";
import { PluginDetailPanel } from "./PluginDetailPanel";
import { PluginListControls, searchablePluginText, usePagedPluginList } from "./PluginListControls";
import { PluginPublisherDialog } from "./PluginPublisherDialog";
import {
  catalogInstallSource,
  githubUrl,
  pluginActionId,
  pluginHasManifestEntry,
  pluginInstallSource,
  pluginSettingsPages,
  pluginToolsTabs,
  type PluginView,
} from "./pluginUtils";
import "./PluginManagerPage.css";

const INSTALLED_PLUGIN_PAGE_SIZE = 8;

function normalizePluginKey(value: string | null | undefined) {
  return (value ?? "")
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\/github\.com\//, "")
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function moduleToken(value: string | null | undefined) {
  const moduleName = (value ?? "").split(":", 1)[0] ?? "";
  const parts = moduleName.split(".").filter(Boolean);
  if (!parts.length) {
    return "";
  }
  if (parts.at(-1) === "plugin" && parts.length > 1) {
    return parts.at(-2) ?? "";
  }
  return parts.at(-1) ?? "";
}

function installedPluginKeys(plugin: PluginManifest) {
  return new Set(
    [
      plugin.id,
      plugin.title,
      plugin.directory?.split(/[\\/]/).filter(Boolean).at(-1),
      moduleToken(plugin.entry),
      plugin.install?.sourceLabel,
      plugin.install?.repo,
      plugin.install?.entry,
    ]
      .map(normalizePluginKey)
      .filter(Boolean),
  );
}

function catalogPluginKeys(plugin: PluginCatalogItem) {
  return new Set(
    [
      plugin.id,
      plugin.name,
      plugin.displayName,
      (plugin as PluginCatalogItem & { display_name?: string }).display_name,
      plugin.repo,
      moduleToken(plugin.entry),
    ]
      .map(normalizePluginKey)
      .filter(Boolean),
  );
}

function findInstalledCatalogMatch(plugin: PluginManifest, catalogItems: PluginCatalogItem[]) {
  const installedKeys = installedPluginKeys(plugin);
  return catalogItems.find((item) => {
    for (const key of catalogPluginKeys(item)) {
      if (installedKeys.has(key)) {
        return true;
      }
    }
    return false;
  });
}

function findCatalogInstalledMatch(catalog: PluginCatalogItem, plugins: PluginManifest[]) {
  const catalogKeys = catalogPluginKeys(catalog);
  return plugins.find((plugin) => {
    for (const key of installedPluginKeys(plugin)) {
      if (catalogKeys.has(key)) {
        return true;
      }
    }
    return false;
  });
}

function catalogDisplayName(plugin: PluginCatalogItem | null | undefined) {
  const raw = plugin as (PluginCatalogItem & { display_name?: string; title?: string }) | null | undefined;
  return plugin?.displayName || raw?.display_name || raw?.title || plugin?.name || "";
}

function installedDisplayName(plugin: PluginManifest, catalog: PluginCatalogItem | undefined) {
  const catalogName = catalogDisplayName(catalog);
  if (catalogName && catalogName !== catalog?.name) {
    return catalogName;
  }
  if (plugin.title && plugin.title !== plugin.id) {
    return plugin.title;
  }
  return catalogName || plugin.title || plugin.id;
}

function installedTechnicalName(plugin: PluginManifest, catalog: PluginCatalogItem | undefined, displayName: string) {
  if (catalog?.name && catalog.name !== displayName) {
    return catalog.name;
  }
  if (plugin.id && plugin.id !== displayName) {
    return plugin.id;
  }
  if (plugin.title && plugin.title !== displayName) {
    return plugin.title;
  }
  return "";
}

function catalogDescription(plugin: PluginCatalogItem | null | undefined) {
  return plugin?.shortDescription || plugin?.description || "";
}

function versionLabel(value: string | null | undefined) {
  return (value ?? "").trim().replace(/^v/i, "");
}

function parseVersionParts(value: string | null | undefined) {
  const raw = versionLabel(value);
  if (!raw || raw === "built-in" || raw === "preview" || raw === "未标注") {
    return null;
  }
  const parts = raw
    .split(/[^\d]+/)
    .filter(Boolean)
    .map(Number);
  return parts.length && parts.every(Number.isFinite) ? parts : null;
}

function compareVersion(remote: string | null | undefined, local: string | null | undefined) {
  const remoteParts = parseVersionParts(remote);
  const localParts = parseVersionParts(local);
  if (!remoteParts || !localParts) {
    return 0;
  }
  const length = Math.max(remoteParts.length, localParts.length);
  for (let index = 0; index < length; index += 1) {
    const diff = (remoteParts[index] ?? 0) - (localParts[index] ?? 0);
    if (diff !== 0) {
      return diff;
    }
  }
  return 0;
}

function normalizedPackageHash(value: string | null | undefined) {
  return (value ?? "").trim().toLowerCase();
}

function catalogPackageHash(catalog: PluginCatalogItem | null | undefined) {
  return normalizedPackageHash(catalog?.packageSha256 || catalog?.sha256);
}

function installedPackageHash(plugin: PluginManifest | null | undefined) {
  return normalizedPackageHash(plugin?.install?.packageSha256);
}

function hasVersionUpdate(remote: string | null | undefined, local: string | null | undefined) {
  const remoteText = versionLabel(remote);
  const localText = versionLabel(local);
  if (!remoteText || remoteText === localText) {
    return false;
  }
  const comparison = compareVersion(remote, local);
  if (comparison !== 0) {
    return comparison > 0;
  }
  return parseVersionParts(remote) !== null && parseVersionParts(local) === null;
}

function hasCatalogUpdate(catalog: PluginCatalogItem | null | undefined, plugin: PluginManifest | null | undefined) {
  const remoteHash = catalogPackageHash(catalog);
  const localHash = installedPackageHash(plugin);
  if (remoteHash && localHash) {
    return remoteHash !== localHash;
  }
  return hasVersionUpdate(catalog?.version, plugin?.version);
}

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
  const [pendingCatalogInstall, setPendingCatalogInstall] = useState<PluginCatalogItem | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<PluginManifest | null>(null);
  const [detailPlugin, setDetailPlugin] = useState<PluginManifest | null>(null);
  const [pluginReloadPending, setPluginReloadPending] = useState(false);
  const [publisherOpen, setPublisherOpen] = useState(false);
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
    enabled: view !== "mcp",
    queryFn: listPluginCatalog,
    queryKey: pluginCatalogQueryKey,
    retry: 1,
  });
  const catalogItems = useMemo(() => catalogQuery.data ?? [], [catalogQuery.data]);

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

  const openCatalogInstallDialog = useCallback(
    (plugin: PluginCatalogItem) => {
      if (installMutation.isPending) {
        return;
      }
      installMutation.reset();
      setInstallTask(null);
      setInstallingSource("");
      setPendingCatalogInstall(plugin);
    },
    [installMutation],
  );

  const closeCatalogInstallDialog = useCallback(() => {
    if (installMutation.isPending) {
      return;
    }
    installMutation.reset();
    setInstallTask(null);
    setInstallingSource("");
    setPendingCatalogInstall(null);
  }, [installMutation]);

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
  const getCatalogInstallState = useCallback(
    (catalog: PluginCatalogItem) => {
      const installedPlugin = findCatalogInstalledMatch(catalog, data);
      const installed = Boolean(catalog.installed || installedPlugin);
      const downloaded = Boolean(catalog.downloaded);
      return {
        downloaded,
        installed,
        updateAvailable: (downloaded || installed) && hasCatalogUpdate(catalog, installedPlugin ?? null),
      };
    },
    [data],
  );

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
          <Button
            icon={<Send aria-hidden className="button__icon" />}
            onClick={() => setPublisherOpen(true)}
            variant="primary"
          >
            {t("plugin.publisher.open")}
          </Button>
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
          getCatalogInstallState={getCatalogInstallState}
          installMutation={installMutation}
          installingSource={installingSource}
          onOpenCatalogInstall={openCatalogInstallDialog}
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
                const catalog = findInstalledCatalogMatch(plugin, catalogItems);
                const displayTitle = installedDisplayName(plugin, catalog);
                const secondaryTitle = installedTechnicalName(plugin, catalog, displayTitle);
                const description =
                  !loaded && plugin.enabled
                    ? plugin.loadError || t("plugin.loadError.unavailable")
                    : catalogDescription(catalog) || plugin.description;
                const docsUrl = catalog?.readmeUrl || (catalog?.repo ? githubUrl(catalog.repo) : "");
                const authorUrl = catalog?.socialLink?.trim() || "";
                const updateSource = catalog ? catalogInstallSource(catalog) : "";
                const updateAvailable = hasCatalogUpdate(catalog, plugin);
                const updateVersion = versionLabel(catalog?.version);
                const updateLabel = updateVersion ? `可更新到 ${updateVersion}` : "可更新";
                const statusLabel = !plugin.enabled
                  ? t("plugin.status.disabled")
                  : loaded
                    ? t("plugin.status.enabled")
                    : t("plugin.status.unavailable");
                return (
                  <article className="plugin-card" key={plugin.id}>
                    <div className="plugin-card__header">
                      <div className="plugin-card__logo" aria-hidden="true">
                        {catalog?.logo ? (
                          <img alt="" src={catalog.logo} />
                        ) : (
                          <img alt="" className="plugin-default-logo" src={defaultPluginLogoUrl} />
                        )}
                      </div>
                      <div className="plugin-card__identity">
                        <div className="plugin-card__title-row">
                          <div className="plugin-card__title">
                            <strong>{displayTitle}</strong>
                            {secondaryTitle ? <span className="inline-status">{secondaryTitle}</span> : null}
                          </div>
                          <span className="plugin-card__status" data-enabled={plugin.enabled} data-loaded={loaded}>
                            {statusLabel}
                          </span>
                        </div>
                        <div className="plugin-card__badges">
                          <span className="plugin-card__badge">版本 {versionLabel(plugin.version) || "-"}</span>
                          {updateAvailable && updateSource ? (
                            <button
                              className="plugin-card__badge plugin-card__badge--update"
                              disabled={installMutation.isPending}
                              onClick={() => catalog && openCatalogInstallDialog(catalog)}
                              title={updateLabel}
                              type="button"
                            >
                              <ArrowUpCircle aria-hidden size={13} />
                              {updateLabel}
                            </button>
                          ) : null}
                          {catalog?.lowestShinsekaiVersion ? (
                            <span className="plugin-card__badge plugin-card__badge--support">
                              支持 {catalog.lowestShinsekaiVersion}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    {description ? <p className="plugin-card__description">{description}</p> : null}
                    <div className="plugin-card__meta">
                      <span>
                        {t("plugin.id")}: {plugin.id}
                      </span>
                      {plugin.author && authorUrl ? (
                        <button
                          className="plugin-inline-link"
                          onClick={() => openExternal(authorUrl)}
                          title={authorUrl}
                          type="button"
                        >
                          {t("plugin.author")}: {plugin.author}
                        </button>
                      ) : plugin.author ? (
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
                        aria-label={t("plugin.action.uninstall")}
                        disabled={pluginBusy || !pluginHasManifestEntry(plugin)}
                        icon={<Trash2 aria-hidden className="button__icon" />}
                        onClick={() => setPendingUninstall(plugin)}
                        variant="danger"
                      >
                        {t("plugin.action.uninstall")}
                      </Button>
                      <Button
                        aria-label={plugin.enabled ? t("plugin.toggle.disable") : t("plugin.toggle.enable")}
                        disabled={pluginBusy || !pluginHasManifestEntry(plugin)}
                        icon={<Power aria-hidden className="button__icon" />}
                        onClick={() => toggleMutation.mutate({ enabled: !plugin.enabled, id: pluginActionId(plugin) })}
                        variant={plugin.enabled ? "default" : "ghost"}
                      >
                        {plugin.enabled ? t("plugin.toggle.disable") : t("plugin.toggle.enable")}
                      </Button>
                      {docsUrl ? (
                        <Button
                          icon={<BookOpen aria-hidden className="button__icon" />}
                          onClick={() => openExternal(docsUrl)}
                          variant="ghost"
                        >
                          文档
                        </Button>
                      ) : null}
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
      <PluginCatalogInstallDialog
        installMutation={installMutation}
        installTask={installTask}
        onClose={closeCatalogInstallDialog}
        plugin={pendingCatalogInstall}
      />
      <PluginPublisherDialog onClose={() => setPublisherOpen(false)} open={publisherOpen} />
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
  const baseUrl = bridgeUrl.replace(/\/$/, "");
  const url = `${baseUrl}/api/health`;
  const started = Date.now();
  let lastError: unknown;

  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      const payload = await response.json().catch(() => null);
      if (response.ok && payload?.ok === true) {
        const status = normalizePluginLoadStatus(payload?.plugins) ?? (await fetchPluginLoadStatus(baseUrl));
        if (!status || status.status === "ready") {
          return;
        }
        if (status.status === "error") {
          throw new PluginLoadTerminalError(status.error || "Plugin service reload failed.");
        }
        lastError = new Error(`Plugin service is still ${status.status}.`);
      } else {
        lastError = new Error(`Plugin service health check failed: ${response.status}`);
      }
    } catch (error) {
      if (error instanceof PluginLoadTerminalError) {
        throw error;
      }
      lastError = error;
    }
    await delayPluginReload(160);
  }

  throw new Error(lastError instanceof Error ? lastError.message : `Timed out waiting for plugin service at ${url}`);
}

class PluginLoadTerminalError extends Error {}

type PluginLoadStatus = {
  error?: string;
  status?: string;
};

async function fetchPluginLoadStatus(baseUrl: string): Promise<PluginLoadStatus | null> {
  try {
    const response = await fetch(`${baseUrl}/api/plugins/status`, { cache: "no-store" });
    if (response.status === 404) {
      return null;
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return null;
    }
    return normalizePluginLoadStatus(payload);
  } catch {
    return null;
  }
}

function normalizePluginLoadStatus(value: unknown): PluginLoadStatus | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const status = typeof record.status === "string" ? record.status : "";
  if (!status) {
    return null;
  }
  return {
    error: typeof record.error === "string" ? record.error : "",
    status,
  };
}

function delayPluginReload(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
