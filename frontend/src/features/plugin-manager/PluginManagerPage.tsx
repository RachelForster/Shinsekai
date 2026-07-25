import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpCircle, BookOpen, Power, RotateCcw, Send, Settings, Trash2 } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

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
import { reloadPluginService } from "./pluginReload";
import "./PluginManagerPage.css";

const INSTALLED_PLUGIN_PAGE_SIZE = 8;
const PLUGIN_DEVELOPER_DOCS_URL = "https://plugins.shinsekai.studio/docs/plugin";

interface PluginRouteReturnTo {
  hash?: string;
  pathname: string;
  search?: string;
  state?: unknown;
}

interface PluginRouteState {
  pageId?: unknown;
  pluginId?: unknown;
  returnTo?: unknown;
}

interface PluginDetailState {
  pageId: string;
  plugin: PluginManifest;
  returnTo: PluginRouteReturnTo | null;
}

function parsePluginRouteReturnTo(value: unknown): PluginRouteReturnTo | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Partial<PluginRouteReturnTo>;
  if (
    typeof candidate.pathname !== "string" ||
    (!candidate.pathname.startsWith("/settings") &&
      candidate.pathname !== "/chat" &&
      candidate.pathname !== "/chat-stage")
  ) {
    return null;
  }
  return {
    hash: typeof candidate.hash === "string" ? candidate.hash : "",
    pathname: candidate.pathname,
    search: typeof candidate.search === "string" ? candidate.search : "",
    state: candidate.state,
  };
}

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

function pluginRouteIntentKey(
  location: Pick<ReturnType<typeof useLocation>, "hash" | "key" | "pathname" | "search">,
  pluginId: string,
  pageId = "",
) {
  return `${location.key}:${location.pathname}${location.search}${location.hash}:${pluginId}:${pageId}`;
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

class PluginInstallReloadError extends Error {
  plugin: PluginManifest;
  reason: unknown;

  constructor(plugin: PluginManifest, reason: unknown) {
    super("Plugin reload after install failed.");
    this.name = "PluginInstallReloadError";
    this.plugin = plugin;
    this.reason = reason;
  }
}

export function PluginManagerPage() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { t } = useI18n();
  const pageRef = useRef<HTMLDivElement | null>(null);
  const headerRef = useRef<HTMLElement | null>(null);
  const pluginsQuery = useQuery({ queryFn: listPlugins, queryKey: pluginsQueryKey });
  const data = pluginsQuery.data ?? [];
  const isLoading = pluginsQuery.isLoading;
  const [view, setView] = useState<PluginView>("installed");
  const [installingSource, setInstallingSource] = useState("");
  const [installTask, setInstallTask] = useState<TaskSnapshot<PluginManifest> | null>(null);
  const [pendingCatalogInstall, setPendingCatalogInstall] = useState<PluginCatalogItem | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<PluginManifest | null>(null);
  const [detail, setDetail] = useState<PluginDetailState | null>(null);
  const consumedRouteIntentRef = useRef("");
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

  useEffect(() => {
    const page = pageRef.current;
    const header = headerRef.current;
    if (!page || !header) {
      return undefined;
    }

    const updateStickyHeaderHeight = () => {
      page.style.setProperty("--plugin-sticky-header-height", `${Math.ceil(header.getBoundingClientRect().height)}px`);
    };

    updateStickyHeaderHeight();
    window.addEventListener("resize", updateStickyHeaderHeight);

    if (typeof ResizeObserver === "undefined") {
      return () => {
        window.removeEventListener("resize", updateStickyHeaderHeight);
      };
    }

    const observer = new ResizeObserver(updateStickyHeaderHeight);
    observer.observe(header);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateStickyHeaderHeight);
    };
  }, []);

  useEffect(() => {
    const state = location.state as PluginRouteState | null;
    const pluginId = typeof state?.pluginId === "string" ? state.pluginId : "";
    const pageId = typeof state?.pageId === "string" ? state.pageId.trim() : "";
    if (!pluginId || !data.length || (detail?.plugin.id === pluginId && detail.pageId === pageId)) {
      return;
    }
    const intentKey = pluginRouteIntentKey(location, pluginId, pageId);
    if (consumedRouteIntentRef.current === intentKey) {
      return;
    }
    const plugin = data.find((item) => item.id === pluginId || pluginActionId(item) === pluginId);
    if (!plugin) {
      return;
    }
    consumedRouteIntentRef.current = intentKey;
    setDetail({ pageId, plugin, returnTo: parsePluginRouteReturnTo(state?.returnTo) });
  }, [data, detail?.pageId, detail?.plugin.id, location, location.state]);

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
    mutationFn: async (input: PluginInstallInput | string) => {
      const plugin = await installPlugin(input, { onTaskUpdate: setInstallTask });
      if (isTauriDesktop()) {
        setPluginReloadPending(true);
        try {
          await reloadPluginService();
        } catch (error) {
          await writeDesktopRestartDebugLog(
            `PluginManagerPage install reload catch: ${desktopRestartErrorMessage(error)}`,
          );
          throw new PluginInstallReloadError(plugin, error);
        }
      }
      return plugin;
    },
    onMutate(input) {
      setInstallTask(null);
      setInstallingSource(pluginInstallSource(input));
    },
    onError(error) {
      if (error instanceof PluginInstallReloadError) {
        queryClient.invalidateQueries({ queryKey: pluginsQueryKey });
        queryClient.invalidateQueries({ queryKey: pluginCatalogQueryKey });
        showToast({
          kind: "error",
          message: `${error.plugin.title}: ${desktopRestartErrorMessage(error.reason) || t("plugin.appRestart.failed")}`,
          title: t("plugin.appRestart.failed"),
        });
        return;
      }
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
        message: `${plugin.title}。${isTauriDesktop() ? t("plugin.toast.activated") : t("plugin.toast.restartHint")}`,
        title: t("plugin.toast.installSuccess"),
      });
    },
    onSettled() {
      setInstallingSource("");
      setPluginReloadPending(false);
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
      await reloadPluginService();
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

  const handleDetailBack = () => {
    if (detail?.returnTo) {
      const { state, ...to } = detail.returnTo;
      setDetail(null);
      navigate(to, { state });
      return;
    }
    setDetail(null);
  };

  if (detail) {
    return <PluginDetailPanel detailPlugin={detail.plugin} initialPageId={detail.pageId} onBack={handleDetailBack} />;
  }

  return (
    <div className="page plugin-page" ref={pageRef}>
      <header className="page__header" ref={headerRef}>
        <div>
          <h1 className="page__title">{t("nav.plugins")}</h1>
          {pluginReloadPending ? (
            <span className="inline-status plugin-reload-status">{t("plugin.appRestart.pending")}</span>
          ) : null}
        </div>
        <div className="page__actions plugin-page__actions">
          <Button
            icon={<BookOpen aria-hidden className="button__icon" />}
            onClick={() => openExternal(PLUGIN_DEVELOPER_DOCS_URL)}
            variant="ghost"
          >
            {t("plugin.action.developerDocs")}
          </Button>
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
                const updateLabel = updateVersion
                  ? t("plugin.updateBadge", { version: updateVersion })
                  : t("plugin.updateBadgeUnknown");
                const hasDocsLink = Boolean(docsUrl);
                const hasPluginSettings = Boolean(pluginSettingsPages(plugin).length || pluginToolsTabs(plugin).length);
                const actionCount = 2 + (hasDocsLink ? 1 : 0) + (hasPluginSettings ? 1 : 0);
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
                          <span className="plugin-card__badge">
                            {t("plugin.versionBadge", { version: versionLabel(plugin.version) || "-" })}
                          </span>
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
                              {t("plugin.supportBadge", { version: catalog.lowestShinsekaiVersion })}
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
                    <div className="plugin-card__actions" data-action-count={actionCount}>
                      <Button
                        aria-label={t("plugin.action.uninstall")}
                        disabled={pluginBusy || !pluginHasManifestEntry(plugin)}
                        icon={<Trash2 aria-hidden className="button__icon" />}
                        onClick={() => setPendingUninstall(plugin)}
                        tooltip={t("plugin.action.uninstall")}
                        variant="danger"
                      >
                        {t("plugin.action.uninstall")}
                      </Button>
                      <Button
                        aria-label={plugin.enabled ? t("plugin.toggle.disable") : t("plugin.toggle.enable")}
                        disabled={pluginBusy || !pluginHasManifestEntry(plugin)}
                        icon={<Power aria-hidden className="button__icon" />}
                        onClick={() => toggleMutation.mutate({ enabled: !plugin.enabled, id: pluginActionId(plugin) })}
                        tooltip={plugin.enabled ? t("plugin.toggle.disable") : t("plugin.toggle.enable")}
                        variant={plugin.enabled ? "default" : "ghost"}
                      >
                        {plugin.enabled ? t("plugin.toggle.disable") : t("plugin.toggle.enable")}
                      </Button>
                      {hasDocsLink ? (
                        <Button
                          icon={<BookOpen aria-hidden className="button__icon" />}
                          onClick={() => openExternal(docsUrl)}
                          tooltip={t("plugin.action.docs")}
                          variant="ghost"
                        >
                          {t("plugin.action.docs")}
                        </Button>
                      ) : null}
                      {hasPluginSettings ? (
                        <Button
                          disabled={pluginBusy || !loaded}
                          icon={<Settings aria-hidden className="button__icon" />}
                          onClick={() => {
                            setDetail({ pageId: "", plugin, returnTo: null });
                          }}
                          tooltip={t("plugin.action.viewConfig")}
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
