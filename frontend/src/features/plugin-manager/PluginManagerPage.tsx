import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DownloadCloud, ExternalLink, Power, RefreshCw, Settings, Trash2 } from "lucide-react";

import {
  installPlugin,
  getAppUpdateInfo,
  listAppUpdateTags,
  listPluginCatalog,
  listPlugins,
  listRepoTags,
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
import { useI18n } from "../../shared/i18n";
import { getPlatform } from "../../shared/platform/platform";
import type { TaskSnapshot } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  DataTable,
  Dialog,
  EmptyState,
  SegmentedTabs,
  Select,
  useToast,
} from "../../shared/ui";
import { McpSettingsPanel } from "./McpSettingsPanel";

type PluginView = "installed" | "discover" | "mcp";

function catalogInstallSource(item: PluginCatalogItem) {
  return item.repo;
}

function githubUrl(repo: string) {
  return repo ? `https://github.com/${repo}` : "";
}

function pluginSettingsPages(plugin: PluginManifest | null) {
  return plugin?.settingsPages ?? [];
}

function pluginToolsTabs(plugin: PluginManifest | null) {
  return plugin?.toolsTabs ?? [];
}

function pluginActionId(plugin: PluginManifest) {
  return plugin.entry || plugin.id;
}

function pluginHasManifestEntry(plugin: PluginManifest) {
  return Boolean(plugin.entry?.trim());
}

function pluginInstallSource(input: PluginInstallInput | string) {
  return typeof input === "string" ? input : input.source;
}

export function PluginManagerPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const { data = [], isLoading } = useQuery({ queryFn: listPlugins, queryKey: pluginsQueryKey });
  const [view, setView] = useState<PluginView>("installed");
  const [installingSource, setInstallingSource] = useState("");
  const [installTask, setInstallTask] = useState<TaskSnapshot<PluginManifest> | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<PluginManifest | null>(null);
  const [detailPlugin, setDetailPlugin] = useState<PluginManifest | null>(null);
  const [pendingAppUpdate, setPendingAppUpdate] = useState(false);
  const [appUpdateRefKind, setAppUpdateRefKind] = useState<AppUpdateRefKind>("latest");
  const [appUpdateTagName, setAppUpdateTagName] = useState("");
  const [appUpdateTask, setAppUpdateTask] = useState<TaskSnapshot<AppUpdateResult> | null>(null);
  const [pendingCatalogInstall, setPendingCatalogInstall] = useState<PluginCatalogItem | null>(null);
  const [catalogRefKind, setCatalogRefKind] = useState<AppUpdateRefKind>("latest");
  const [catalogTagName, setCatalogTagName] = useState("");
  const appUpdateInfoQuery = useQuery({
    enabled: view === "discover",
    queryFn: getAppUpdateInfo,
    queryKey: ["plugins", "app-update", "info"],
  });
  const appUpdateTagsQuery = useQuery({
    enabled: pendingAppUpdate,
    queryFn: listAppUpdateTags,
    queryKey: ["plugins", "app-update", "tags"],
    retry: 1,
  });
  const catalogTagsQuery = useQuery({
    enabled: Boolean(pendingCatalogInstall?.repo),
    queryFn: () => listRepoTags(pendingCatalogInstall?.repo ?? ""),
    queryKey: ["plugins", "repo-tags", pendingCatalogInstall?.repo ?? ""],
    retry: 1,
  });
  const catalogQuery = useQuery({
    enabled: view === "discover",
    queryFn: listPluginCatalog,
    queryKey: pluginCatalogQueryKey,
    retry: 1,
  });

  useEffect(() => {
    if (!appUpdateTagName && appUpdateTagsQuery.data?.[0]) {
      setAppUpdateTagName(appUpdateTagsQuery.data[0]);
    }
  }, [appUpdateTagName, appUpdateTagsQuery.data]);

  useEffect(() => {
    if (!catalogTagName && catalogTagsQuery.data?.[0]) {
      setCatalogTagName(catalogTagsQuery.data[0]);
    }
  }, [catalogTagName, catalogTagsQuery.data]);

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
      setPendingCatalogInstall(null);
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
    mutationFn: () =>
      runAppUpdate(
        { refKind: appUpdateRefKind, tagName: appUpdateRefKind === "tag" ? appUpdateTagName : undefined },
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
      setPendingAppUpdate(false);
    },
    onSuccess(result) {
      queryClient.invalidateQueries({ queryKey: ["plugins", "app-update", "info"] });
      showToast({
        kind: "success",
        message: result.message,
        title: t("plugin.appUpdate.success"),
      });
    },
  });

  const installProgress = installTask?.progress == null ? null : Math.round(installTask.progress * 100);
  const installLogs = installTask?.logs.slice(-6) ?? [];
  const appUpdateProgress = appUpdateTask?.progress == null ? null : Math.round(appUpdateTask.progress * 100);
  const appUpdateLogs = appUpdateTask?.logs.slice(-6) ?? [];
  const appUpdateInfo = appUpdateInfoQuery.data;

  const catalogColumns = [
    {
      header: t("plugin.plugin"),
      key: "name",
      render: (plugin: PluginCatalogItem) => (
        <div>
          <strong>{plugin.name}</strong>
          {plugin.repo ? <div className="inline-status">{plugin.repo}</div> : null}
        </div>
      ),
    },
    {
      header: t("common.author"),
      key: "author",
      render: (plugin: PluginCatalogItem) => plugin.author || "-",
    },
    {
      header: t("common.description"),
      key: "description",
      render: (plugin: PluginCatalogItem) => plugin.description || "-",
    },
    {
      header: t("plugin.table.actionHeader"),
      key: "actions",
      render: (plugin: PluginCatalogItem) => {
        const source = catalogInstallSource(plugin);
        const url = githubUrl(plugin.repo);
        const actionDisabled = !source || installMutation.isPending;
        return (
          <div className="inline-actions">
            <AsyncButton
              disabled={actionDisabled}
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              loading={installMutation.isPending && installingSource === source}
              onClick={() => {
                if (plugin.repo) {
                  setCatalogRefKind("latest");
                  setCatalogTagName("");
                  setPendingCatalogInstall(plugin);
                  return;
                }
                installMutation.mutate(source);
              }}
              variant="primary"
            >
              {plugin.downloaded ? t("plugin.action.update") : t("plugin.action.install")}
            </AsyncButton>
            <Button
              disabled={!url}
              icon={<ExternalLink aria-hidden className="button__icon" />}
              onClick={() => url && getPlatform().files.openExternal(url)}
              variant="ghost"
            >
              {t("plugin.action.openGitHub")}
            </Button>
          </div>
        );
      },
    },
  ];
  const pluginBusy = toggleMutation.isPending || uninstallMutation.isPending;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("nav.plugins")}</h1>
          <p className="page__description">{t("plugin.description")}</p>
        </div>
      </header>

      <SegmentedTabs
        ariaLabel={t("common.subpages")}
        items={[
          { id: "installed", label: t("plugin.installed.title") },
          { id: "discover", label: t("plugin.catalog.title") },
          { id: "mcp", label: "MCP" },
        ]}
        onChange={setView}
        value={view}
      />

      {view === "installed" ? (
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
          {!isLoading && data.length ? (
            <div className="plugin-card-grid">
              {data.map((plugin) => {
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
          {!isLoading && !data.length ? (
            <EmptyState title={t("plugin.installed.emptyTitle")} body={t("plugin.installed.emptyBody")} />
          ) : null}
        </section>
      ) : view === "discover" ? (
        <section className="section">
          <div className="section__header">
            <div>
              <h2 className="section__title">{t("plugin.catalog.title")}</h2>
              <span className="inline-status">
                {appUpdateInfo?.version
                  ? t("plugin.appUpdate.version", { version: appUpdateInfo.version })
                  : t("plugin.appUpdate.versionUnknown")}
              </span>
            </div>
            <div className="inline-actions">
              <Button
                disabled={appUpdateMutation.isPending}
                icon={<DownloadCloud aria-hidden className="button__icon" />}
                onClick={() => setPendingAppUpdate(true)}
                variant="ghost"
              >
                {t("plugin.appUpdate.button")}
              </Button>
              <Button
                icon={<RefreshCw aria-hidden className="button__icon" />}
                onClick={() => catalogQuery.refetch()}
                variant="ghost"
              >
                {t("common.refresh")}
              </Button>
            </div>
          </div>
          {appUpdateTask ? (
            <div className="task-progress" role="status" aria-live="polite">
              <div className="task-progress__meta">
                <strong>{appUpdateTask.phase}</strong>
                <span>{appUpdateProgress == null ? appUpdateTask.status : `${appUpdateProgress}%`}</span>
              </div>
              {appUpdateProgress == null ? null : (
                <div className="task-progress__track" aria-hidden>
                  <span className="task-progress__fill" style={{ width: `${appUpdateProgress}%` }} />
                </div>
              )}
              <div className="task-progress__message">{appUpdateTask.message || appUpdateTask.status}</div>
              {appUpdateLogs.length ? <pre className="task-progress__log">{appUpdateLogs.join("\n")}</pre> : null}
            </div>
          ) : null}
          {installTask ? (
            <div className="task-progress" role="status" aria-live="polite">
              <div className="task-progress__meta">
                <strong>{installTask.phase}</strong>
                <span>{installProgress == null ? installTask.status : `${installProgress}%`}</span>
              </div>
              {installProgress == null ? null : (
                <div className="task-progress__track" aria-hidden>
                  <span className="task-progress__fill" style={{ width: `${installProgress}%` }} />
                </div>
              )}
              <div className="task-progress__message">{installTask.message || installTask.status}</div>
              {installLogs.length ? <pre className="task-progress__log">{installLogs.join("\n")}</pre> : null}
            </div>
          ) : null}
          {catalogQuery.isLoading ? <EmptyState title={t("plugin.catalog.loading")} /> : null}
          {catalogQuery.isError ? (
            <EmptyState
              action={
                <Button
                  icon={<RefreshCw aria-hidden className="button__icon" />}
                  onClick={() => catalogQuery.refetch()}
                >
                  {t("common.retry")}
                </Button>
              }
              body={catalogQuery.error instanceof Error ? catalogQuery.error.message : t("plugin.catalog.errorBody")}
              title={t("plugin.catalog.errorTitle")}
            />
          ) : null}
          {catalogQuery.data?.length ? (
            <DataTable
              columns={catalogColumns}
              getRowKey={(plugin) => plugin.repo || plugin.entry}
              rows={catalogQuery.data}
            />
          ) : null}
          {!catalogQuery.isLoading && !catalogQuery.isError && !catalogQuery.data?.length ? (
            <EmptyState title={t("plugin.catalog.emptyTitle")} body={t("plugin.catalog.emptyBody")} />
          ) : null}
        </section>
      ) : (
        <McpSettingsPanel />
      )}

      <Dialog
        closeLabel={t("common.close")}
        footer={
          <>
            <Button onClick={() => setPendingCatalogInstall(null)}>{t("common.cancel")}</Button>
            <AsyncButton
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              loading={installMutation.isPending}
              onClick={() => {
                const source = pendingCatalogInstall ? catalogInstallSource(pendingCatalogInstall) : "";
                if (!source) {
                  return;
                }
                if (catalogRefKind === "tag" && !catalogTagName.trim()) {
                  showToast({
                    kind: "error",
                    message: t("plugin.appUpdate.tagInvalid"),
                    title: t("plugin.installRef.title"),
                  });
                  return;
                }
                installMutation.mutate({
                  overwrite: Boolean(pendingCatalogInstall?.downloaded),
                  refKind: catalogRefKind,
                  source,
                  tagName: catalogRefKind === "tag" ? catalogTagName : undefined,
                });
              }}
              variant="primary"
            >
              {pendingCatalogInstall?.downloaded ? t("plugin.action.update") : t("plugin.action.install")}
            </AsyncButton>
          </>
        }
        onClose={() => setPendingCatalogInstall(null)}
        open={Boolean(pendingCatalogInstall)}
        title={t("plugin.installRef.title")}
      >
        <div className="plugin-detail">
          <p className="inline-status">{t("plugin.appUpdate.repo", { repo: pendingCatalogInstall?.repo ?? "-" })}</p>
          <label className="field-row field-row--stack">
            <span className="field-row__label">{t("plugin.appUpdate.ref")}</span>
            <span className="field-row__control">
              <Select
                onChange={(event) => {
                  const value = event.target.value;
                  if (value === "latest" || value === "head") {
                    setCatalogRefKind(value);
                    return;
                  }
                  setCatalogRefKind("tag");
                  setCatalogTagName(value.replace(/^tag:/, ""));
                }}
                value={catalogRefKind === "tag" ? `tag:${catalogTagName}` : catalogRefKind}
              >
                <option value="latest">{t("plugin.appUpdate.refLatest")}</option>
                <option value="head">{t("plugin.appUpdate.refHead")}</option>
                {catalogTagsQuery.data?.map((tag) => (
                  <option key={tag} value={`tag:${tag}`}>
                    {tag}
                  </option>
                ))}
              </Select>
              {catalogTagsQuery.isLoading ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsLoading")}</span>
              ) : null}
              {!catalogTagsQuery.isLoading && !catalogTagsQuery.data?.length ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsEmpty")}</span>
              ) : null}
            </span>
          </label>
        </div>
      </Dialog>

      <Dialog
        closeLabel={t("common.close")}
        footer={
          <>
            <Button onClick={() => setPendingAppUpdate(false)}>{t("common.cancel")}</Button>
            <AsyncButton
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              loading={appUpdateMutation.isPending}
              onClick={() => {
                if (appUpdateRefKind === "tag" && !appUpdateTagName.trim()) {
                  showToast({
                    kind: "error",
                    message: t("plugin.appUpdate.tagInvalid"),
                    title: t("plugin.appUpdate.title"),
                  });
                  return;
                }
                appUpdateMutation.mutate();
              }}
              variant="danger"
            >
              {t("plugin.appUpdate.confirm")}
            </AsyncButton>
          </>
        }
        onClose={() => setPendingAppUpdate(false)}
        open={pendingAppUpdate}
        title={t("plugin.appUpdate.title")}
      >
        <div className="plugin-detail">
          <p className="plugin-card__description">{t("plugin.appUpdate.warning")}</p>
          <p className="inline-status">{t("plugin.appUpdate.repo", { repo: appUpdateInfo?.repo ?? "-" })}</p>
          <label className="field-row field-row--stack">
            <span className="field-row__label">{t("plugin.appUpdate.ref")}</span>
            <span className="field-row__control">
              <Select
                onChange={(event) => {
                  const value = event.target.value;
                  if (value === "latest" || value === "head") {
                    setAppUpdateRefKind(value);
                    return;
                  }
                  setAppUpdateRefKind("tag");
                  setAppUpdateTagName(value.replace(/^tag:/, ""));
                }}
                value={appUpdateRefKind === "tag" ? `tag:${appUpdateTagName}` : appUpdateRefKind}
              >
                <option value="latest">{t("plugin.appUpdate.refLatest")}</option>
                <option value="head">{t("plugin.appUpdate.refHead")}</option>
                {appUpdateTagsQuery.data?.map((tag) => (
                  <option key={tag} value={`tag:${tag}`}>
                    {tag}
                  </option>
                ))}
              </Select>
              {appUpdateTagsQuery.isLoading ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsLoading")}</span>
              ) : null}
              {!appUpdateTagsQuery.isLoading && !appUpdateTagsQuery.data?.length ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsEmpty")}</span>
              ) : null}
            </span>
          </label>
        </div>
      </Dialog>

      <Dialog
        closeLabel={t("common.close")}
        onClose={() => setDetailPlugin(null)}
        open={Boolean(detailPlugin)}
        title={t("plugin.detail.title", { title: detailPlugin?.title ?? "" })}
      >
        <div className="plugin-detail">
          {pluginSettingsPages(detailPlugin).length ? (
            <div className="plugin-detail__group">
              <strong>{t("plugin.detail.settingsPages")}</strong>
              <ul>
                {pluginSettingsPages(detailPlugin).map((label) => (
                  <li key={label}>{label}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {pluginToolsTabs(detailPlugin).length ? (
            <div className="plugin-detail__group">
              <strong>{t("plugin.detail.toolsTabs")}</strong>
              <ul>
                {pluginToolsTabs(detailPlugin).map((label) => (
                  <li key={label}>{label}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {!pluginSettingsPages(detailPlugin).length && !pluginToolsTabs(detailPlugin).length ? (
            <p className="inline-status">{t("plugin.detail.noUi")}</p>
          ) : null}
        </div>
      </Dialog>

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
