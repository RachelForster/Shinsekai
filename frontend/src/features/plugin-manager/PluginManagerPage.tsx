import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, DownloadCloud, ExternalLink, Power, RefreshCw, Save, Settings, Trash2 } from "lucide-react";

import {
  getPluginUiDetail,
  installPlugin,
  getAppUpdateInfo,
  listAppUpdateTags,
  listPluginCatalog,
  listPlugins,
  listRepoTags,
  pluginCatalogQueryKey,
  pluginUiQueryKey,
  pluginsQueryKey,
  runAppUpdate,
  savePluginUiConfig,
  setPluginEnabled,
  uninstallPlugin,
} from "../../entities/plugin/repository";
import type {
  AppUpdateRefKind,
  AppUpdateResult,
  PluginConfigFieldType,
  PluginConfigGroupSchema,
  PluginCatalogItem,
  PluginInstallInput,
  PluginManifest,
  PluginUIPage,
} from "../../entities/plugin/types";
import { openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import type { FieldKind, FormGroupSchema } from "../../shared/ui/formSchema";
import {
  AlertDialog,
  AsyncButton,
  Button,
  DataTable,
  Dialog,
  EmptyState,
  QueryErrorState,
  SchemaDrivenForm,
  SegmentedTabs,
  Select,
  useToast,
} from "../../shared/ui";
import { McpSettingsPanel } from "./McpSettingsPanel";

type PluginView = "installed" | "discover" | "mcp";
type PluginConfigDraft = Record<string, unknown>;

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

function pluginUiPageKey(page: PluginUIPage) {
  return `${page.kind}:${page.id}`;
}

function fallbackPluginUiPages(plugin: PluginManifest | null): PluginUIPage[] {
  if (!plugin) {
    return [];
  }
  const settingsPages = plugin.settingsPages.map((title, index) => ({
    id: `settings-${index}`,
    kind: "settings" as const,
    order: index,
    pluginId: plugin.id,
    pluginVersion: plugin.version,
    title,
    unavailableReason: "",
  }));
  const toolsPages = plugin.toolsTabs.map((title, index) => ({
    id: `tools-${index}`,
    kind: "tools" as const,
    order: settingsPages.length + index,
    pluginId: plugin.id,
    pluginVersion: plugin.version,
    title,
    unavailableReason: "",
  }));
  return [...settingsPages, ...toolsPages];
}

function pluginFieldTypeToFormType(type: PluginConfigFieldType): FieldKind {
  if (type === "boolean") {
    return "checkbox";
  }
  return type;
}

function pluginConfigGroupsToFormGroups(groups: PluginConfigGroupSchema[]): Array<FormGroupSchema<PluginConfigDraft>> {
  return groups.map((group) => ({
    columns: 1,
    description: group.description,
    fields: group.fields.map((field) => ({
      defaultValue: field.defaultValue,
      description: field.description,
      label: field.label,
      max: field.max,
      min: field.min,
      name: field.key,
      options: field.options,
      placeholder: field.placeholder,
      required: field.required,
      span: field.span,
      step: field.step,
      type: pluginFieldTypeToFormType(field.type),
    })),
    id: group.id,
    title: group.title,
  }));
}

function pluginConfigInitialValues(page: PluginUIPage): PluginConfigDraft {
  const values = page.values ?? {};
  const draft: PluginConfigDraft = {};
  for (const group of page.schema ?? []) {
    for (const field of group.fields) {
      draft[field.key] = Object.prototype.hasOwnProperty.call(values, field.key)
        ? values[field.key]
        : field.defaultValue;
    }
  }
  return draft;
}

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
  const [pendingAppUpdate, setPendingAppUpdate] = useState(false);
  const [appUpdateRefKind, setAppUpdateRefKind] = useState<AppUpdateRefKind>("latest");
  const [appUpdateTagName, setAppUpdateTagName] = useState("");
  const [appUpdateTask, setAppUpdateTask] = useState<TaskSnapshot<AppUpdateResult> | null>(null);
  const [pendingCatalogInstall, setPendingCatalogInstall] = useState<PluginCatalogItem | null>(null);
  const [catalogRefKind, setCatalogRefKind] = useState<AppUpdateRefKind>("latest");
  const [catalogTagName, setCatalogTagName] = useState("");
  const [activeDetailPageId, setActiveDetailPageId] = useState("");
  const detailLookupId = detailPlugin ? pluginActionId(detailPlugin) : "";
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
  const pluginDetailQuery = useQuery({
    enabled: Boolean(detailLookupId),
    queryFn: () => getPluginUiDetail(detailLookupId),
    queryKey: pluginUiQueryKey(detailLookupId),
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
  const fallbackDetailPages = useMemo(() => fallbackPluginUiPages(detailPlugin), [detailPlugin]);
  const detailPages = pluginDetailQuery.data?.pages ?? fallbackDetailPages;
  const detailPageSignature = detailPages.map(pluginUiPageKey).join("|");

  useEffect(() => {
    if (!detailPlugin) {
      setActiveDetailPageId("");
      return;
    }
    const pageKeys = detailPages.map(pluginUiPageKey);
    if (pageKeys.length && !pageKeys.includes(activeDetailPageId)) {
      setActiveDetailPageId(pageKeys[0]);
    }
  }, [activeDetailPageId, detailPageSignature, detailPages, detailPlugin]);

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
              onClick={() => url && openExternal(url)}
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
  const detailPluginRow = pluginDetailQuery.data?.plugin ?? detailPlugin;
  const activeDetailPage = detailPages.find((page) => pluginUiPageKey(page) === activeDetailPageId) ?? detailPages[0];

  if (detailPlugin && detailPluginRow) {
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
              onClick={() => setDetailPlugin(null)}
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
            {activeDetailPage ? <PluginConfigPanel lookupId={detailLookupId} page={activeDetailPage} /> : null}
          </>
        ) : null}
      </div>
    );
  }

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
          {pluginsQuery.isError ? (
            <QueryErrorState
              error={pluginsQuery.error}
              onRetry={() => void pluginsQuery.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {!isLoading && !pluginsQuery.isError && data.length ? (
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
          {!isLoading && !pluginsQuery.isError && !data.length ? (
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
          {appUpdateInfoQuery.isError ? (
            <QueryErrorState
              body={t("plugin.appUpdate.failed")}
              error={appUpdateInfoQuery.error}
              onRetry={() => void appUpdateInfoQuery.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {catalogQuery.isLoading ? <EmptyState title={t("plugin.catalog.loading")} /> : null}
          {catalogQuery.isError ? (
            <QueryErrorState
              body={t("plugin.catalog.errorBody")}
              error={catalogQuery.error}
              onRetry={() => void catalogQuery.refetch()}
              retryLabel={t("common.retry")}
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
              {catalogTagsQuery.isError ? (
                <span className="field-row__help" role="alert">
                  {catalogTagsQuery.error instanceof Error
                    ? catalogTagsQuery.error.message
                    : t("plugin.appUpdate.tagsEmpty")}
                </span>
              ) : null}
              {!catalogTagsQuery.isLoading && !catalogTagsQuery.isError && !catalogTagsQuery.data?.length ? (
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
              {appUpdateTagsQuery.isError ? (
                <span className="field-row__help" role="alert">
                  {appUpdateTagsQuery.error instanceof Error
                    ? appUpdateTagsQuery.error.message
                    : t("plugin.appUpdate.tagsEmpty")}
                </span>
              ) : null}
              {!appUpdateTagsQuery.isLoading && !appUpdateTagsQuery.isError && !appUpdateTagsQuery.data?.length ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsEmpty")}</span>
              ) : null}
            </span>
          </label>
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
