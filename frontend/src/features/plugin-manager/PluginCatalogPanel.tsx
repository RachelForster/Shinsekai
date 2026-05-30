import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DownloadCloud, ExternalLink, RefreshCw } from "lucide-react";

import {
  getAppUpdateInfo,
  installPlugin,
  listAppUpdateTags,
  listPluginCatalog,
  listRepoTags,
  pluginCatalogQueryKey,
  pluginsQueryKey,
  runAppUpdate,
} from "../../entities/plugin/repository";
import type { AppUpdateRefKind, AppUpdateResult, PluginCatalogItem, PluginInstallInput, PluginManifest } from "../../entities/plugin/types";
import { openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import {
  AsyncButton,
  Button,
  DataTable,
  Dialog,
  EmptyState,
  QueryErrorState,
  Select,
  TaskProgress,
  useToast,
} from "../../shared/ui";
import { catalogInstallSource, githubUrl } from "./pluginUtils";

interface PluginCatalogPanelProps {
  appUpdateMutation: ReturnType<typeof useMutation<AppUpdateResult, Error, { refKind: AppUpdateRefKind; tagName: string }>>;
  appUpdateTask: TaskSnapshot<AppUpdateResult> | null;
  catalogQuery: ReturnType<typeof useQuery<PluginCatalogItem[]>>;
  installMutation: ReturnType<typeof useMutation<PluginManifest, Error, string | PluginInstallInput>>;
  installTask: TaskSnapshot<PluginManifest> | null;
  installingSource: string;
}

export function PluginCatalogPanel({
  appUpdateMutation,
  appUpdateTask,
  catalogQuery,
  installMutation,
  installTask,
  installingSource,
}: PluginCatalogPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();

  const [pendingAppUpdate, setPendingAppUpdate] = useState(false);
  const [appUpdateRefKind, setAppUpdateRefKind] = useState<AppUpdateRefKind>("latest");
  const [appUpdateTagName, setAppUpdateTagName] = useState("");
  const [pendingCatalogInstall, setPendingCatalogInstall] = useState<PluginCatalogItem | null>(null);
  const [catalogRefKind, setCatalogRefKind] = useState<AppUpdateRefKind>("latest");
  const [catalogTagName, setCatalogTagName] = useState("");

  const appUpdateInfoQuery = useQuery({
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

  return (
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
      <TaskProgress task={appUpdateTask} />
      <TaskProgress task={installTask} />
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

      {/* Catalog install ref-picker dialog */}
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
                  showToast({ kind: "error", message: t("plugin.appUpdate.tagInvalid"), title: t("plugin.installRef.title") });
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
                  <option key={tag} value={`tag:${tag}`}>{tag}</option>
                ))}
              </Select>
              {catalogTagsQuery.isLoading ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsLoading")}</span>
              ) : null}
              {catalogTagsQuery.isError ? (
                <span className="field-row__help" role="alert">
                  {catalogTagsQuery.error instanceof Error ? catalogTagsQuery.error.message : t("plugin.appUpdate.tagsEmpty")}
                </span>
              ) : null}
              {!catalogTagsQuery.isLoading && !catalogTagsQuery.isError && !catalogTagsQuery.data?.length ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsEmpty")}</span>
              ) : null}
            </span>
          </label>
        </div>
      </Dialog>

      {/* App update dialog */}
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
                  showToast({ kind: "error", message: t("plugin.appUpdate.tagInvalid"), title: t("plugin.appUpdate.title") });
                  return;
                }
                appUpdateMutation.mutate({ refKind: appUpdateRefKind, tagName: appUpdateTagName });
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
                  <option key={tag} value={`tag:${tag}`}>{tag}</option>
                ))}
              </Select>
              {appUpdateTagsQuery.isLoading ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsLoading")}</span>
              ) : null}
              {appUpdateTagsQuery.isError ? (
                <span className="field-row__help" role="alert">
                  {appUpdateTagsQuery.error instanceof Error ? appUpdateTagsQuery.error.message : t("plugin.appUpdate.tagsEmpty")}
                </span>
              ) : null}
              {!appUpdateTagsQuery.isLoading && !appUpdateTagsQuery.isError && !appUpdateTagsQuery.data?.length ? (
                <span className="field-row__help">{t("plugin.appUpdate.tagsEmpty")}</span>
              ) : null}
            </span>
          </label>
        </div>
      </Dialog>
    </section>
  );
}
