import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Box,
  CheckCircle2,
  Clock3,
  DownloadCloud,
  ExternalLink,
  GitBranch,
  Globe2,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  Star,
  Tag,
  UserRound,
} from "lucide-react";

import {
  getAppUpdateInfo,
  installPlugin,
  listAppUpdateTags,
  listPluginCatalog,
  listRepoTags,
  runAppUpdate,
} from "../../entities/plugin/repository";
import type {
  AppUpdateRefKind,
  AppUpdateResult,
  PluginCatalogItem,
  PluginInstallInput,
  PluginManifest,
} from "../../entities/plugin/types";
import { openExternal } from "../../entities/files/repository";
import {
  checkDesktopUpdate,
  desktopRestartErrorMessage,
  installDesktopUpdate,
  isTauriDesktop,
  onDesktopUpdateProgress,
  type DesktopUpdate,
  type DesktopUpdateProgress,
} from "../../shared/desktop/desktopApi";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import {
  AsyncButton,
  Button,
  Dialog,
  EmptyState,
  QueryErrorState,
  Select,
  TaskProgress,
  useToast,
} from "../../shared/ui";
import defaultPluginLogoUrl from "../../assets/default-plugin-logo.svg";
import { PluginListControls, searchablePluginText, usePagedPluginList } from "./PluginListControls";
import { catalogInstallSource, githubUrl } from "./pluginUtils";

interface PluginCatalogPanelProps {
  appUpdateMutation: ReturnType<
    typeof useMutation<AppUpdateResult, Error, { refKind: AppUpdateRefKind; tagName: string }>
  >;
  appUpdateTask: TaskSnapshot<AppUpdateResult> | null;
  catalogQuery: ReturnType<typeof useQuery<PluginCatalogItem[]>>;
  getCatalogInstallState: (plugin: PluginCatalogItem) => PluginCatalogInstallState;
  installMutation: ReturnType<typeof useMutation<PluginManifest, Error, string | PluginInstallInput>>;
  installingSource: string;
  onOpenCatalogInstall: (plugin: PluginCatalogItem) => void;
}

interface PluginCatalogInstallState {
  downloaded: boolean;
  installed: boolean;
  updateAvailable: boolean;
}

type DesktopUpdateDialogStatus =
  | "checking"
  | "noUpdate"
  | "available"
  | "downloading"
  | "installing"
  | "restartRequired"
  | "error";

type I18nT = ReturnType<typeof useI18n>["t"];
type DesktopUpdateErrorFallback = "plugin.desktopUpdate.checkFailed" | "plugin.desktopUpdate.installFailed";
type PluginTrustState = "verified" | "community" | "pending" | "blocked";

const CATALOG_PAGE_SIZE = 10;

function catalogDisplayName(plugin: PluginCatalogItem) {
  const raw = plugin as PluginCatalogItem & { display_name?: string; title?: string };
  return plugin.displayName || raw.display_name || raw.title || plugin.name || plugin.repo || plugin.entry;
}

function catalogDescription(plugin: PluginCatalogItem) {
  return plugin.shortDescription || plugin.description || "";
}

function catalogTags(plugin: PluginCatalogItem) {
  return plugin.tags ?? [];
}

function catalogAuthorLink(plugin: PluginCatalogItem) {
  return plugin.socialLink?.trim() || "";
}

function hasOfficialPackage(plugin: PluginCatalogItem | null | undefined) {
  return Boolean(plugin?.packageUrl || plugin?.downloadUrl);
}

function formatBytes(value: number | null | undefined) {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) {
    return "";
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function compactSha(value: string | undefined) {
  const raw = (value ?? "").trim();
  return raw.length > 12 ? `${raw.slice(0, 10)}...` : raw;
}

function securityScanPassed(plugin: PluginCatalogItem) {
  const scan = plugin.securityScan;
  if (!scan || typeof scan !== "object") {
    return false;
  }
  return Object.values(scan).some((item) => {
    if (!item || typeof item !== "object") {
      return false;
    }
    return (item as { pass?: unknown }).pass === true;
  });
}

function pluginTrustState(plugin: PluginCatalogItem | null | undefined): PluginTrustState {
  const raw = (plugin?.trustLevel ?? "").trim().toLowerCase();
  if (raw === "blocked") {
    return "blocked";
  }
  if (raw === "verified_update_pending" || raw === "pending_review" || raw === "pending") {
    return "pending";
  }
  if (raw === "verified" && plugin?.verified === true) {
    return "verified";
  }
  return "community";
}

function catalogTrustNotice(plugin: PluginCatalogItem | null | undefined) {
  const state = pluginTrustState(plugin);
  if (state === "community") {
    return {
      body: "该插件尚未经过人工复核，我们不能完全保证插件的稳定性和安全性。使用前请谨慎核查作者、仓库和权限来源。",
      kind: "community",
      title: "Community 插件",
    };
  }
  if (state === "pending") {
    return {
      body: "该插件曾通过人工复核，但当前版本或提交仍在等待复核。建议确认更新内容与来源后再安装。",
      kind: "pending",
      title: "待复核版本",
    };
  }
  if (state === "blocked") {
    return {
      body: "该插件已从索引下架或被标记为不建议安装。请刷新索引，或联系维护者确认后再处理。",
      kind: "blocked",
      title: "已下架",
    };
  }
  return null;
}

function catalogKey(plugin: PluginCatalogItem) {
  return plugin.id || plugin.name || plugin.repo || plugin.entry;
}

function CatalogTrustBadge({ plugin }: { plugin: PluginCatalogItem }) {
  const state = pluginTrustState(plugin);
  if (state === "verified") {
    return (
      <span className="plugin-market-badge plugin-market-badge--trust-verified">
        <ShieldCheck aria-hidden size={13} />
        Verified
      </span>
    );
  }
  return (
    <span className="plugin-market-badge plugin-market-badge--trust-community">
      <Globe2 aria-hidden size={13} />
      Community
    </span>
  );
}

interface PluginCatalogInstallDialogProps {
  installMutation: ReturnType<typeof useMutation<PluginManifest, Error, string | PluginInstallInput>>;
  installTask: TaskSnapshot<PluginManifest> | null;
  onClose: () => void;
  plugin: PluginCatalogItem | null;
}

export function PluginCatalogInstallDialog({
  installMutation,
  installTask,
  onClose,
  plugin,
}: PluginCatalogInstallDialogProps) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [catalogRefKind, setCatalogRefKind] = useState<AppUpdateRefKind>("latest");
  const [catalogTagName, setCatalogTagName] = useState("");
  const pluginKey = plugin ? catalogKey(plugin) : "";
  const officialPackage = hasOfficialPackage(plugin);
  const installDone = Boolean(plugin) && installMutation.isSuccess && !installMutation.isPending;
  const installNotice = catalogTrustNotice(plugin);
  const installAsUpdate = Boolean(plugin?.downloaded || plugin?.installed);
  const catalogTagsQuery = useQuery({
    enabled: Boolean(plugin?.repo) && !officialPackage,
    queryFn: () => listRepoTags(plugin?.repo ?? ""),
    queryKey: ["plugins", "catalog", "tags", plugin?.repo ?? ""],
    retry: 1,
  });

  useEffect(() => {
    setCatalogRefKind("latest");
    setCatalogTagName("");
  }, [pluginKey]);

  useEffect(() => {
    if (!catalogTagName && catalogTagsQuery.data?.[0]) {
      setCatalogTagName(catalogTagsQuery.data[0]);
    }
  }, [catalogTagName, catalogTagsQuery.data]);

  const closeDialog = () => {
    if (installMutation.isPending) {
      return;
    }
    onClose();
  };

  const startInstall = () => {
    const source = plugin ? catalogInstallSource(plugin) : "";
    if (!plugin || !source) {
      return;
    }
    if (!officialPackage && catalogRefKind === "tag" && !catalogTagName.trim()) {
      showToast({
        kind: "error",
        message: t("plugin.appUpdate.tagInvalid"),
        title: t("plugin.installRef.title"),
      });
      return;
    }
    installMutation.mutate({
      overwrite: installAsUpdate,
      refKind: officialPackage ? "latest" : catalogRefKind,
      source,
      tagName: !officialPackage && catalogRefKind === "tag" ? catalogTagName : undefined,
    });
  };

  return (
    <Dialog
      bodyClassName="plugin-market-install-dialog__body"
      className="plugin-market-install-dialog"
      closeLabel={t("common.close")}
      footer={
        installDone ? (
          <Button onClick={closeDialog} variant="primary">
            {t("common.confirm")}
          </Button>
        ) : (
          <>
            <Button onClick={closeDialog}>{t("common.cancel")}</Button>
            <AsyncButton
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              loading={installMutation.isPending}
              onClick={startInstall}
              variant="primary"
            >
              {installAsUpdate ? t("plugin.action.update") : t("plugin.action.install")}
            </AsyncButton>
          </>
        )
      }
      onClose={closeDialog}
      open={Boolean(plugin)}
      title={t("plugin.installRef.title")}
    >
      <div className="plugin-detail">
        {plugin ? (
          <div className="plugin-market-install-summary">
            <div className="plugin-market-card__header">
              <div className="plugin-market-card__logo" aria-hidden="true">
                {plugin.logo ? (
                  <img alt="" src={plugin.logo} />
                ) : (
                  <img alt="" className="plugin-default-logo" src={defaultPluginLogoUrl} />
                )}
              </div>
              <div className="plugin-market-card__identity">
                <div className="plugin-market-card__title-row">
                  <h3>{catalogDisplayName(plugin)}</h3>
                  {plugin.version ? (
                    <span className="plugin-market-badge">v{plugin.version.replace(/^v/i, "")}</span>
                  ) : null}
                  <CatalogTrustBadge plugin={plugin} />
                </div>
                <span className="plugin-market-card__id">{plugin.name}</span>
              </div>
            </div>
            <p className="plugin-card__description">{catalogDescription(plugin) || plugin.repo || plugin.entry}</p>
            {installNotice ? (
              <div
                className="plugin-market-install-warning"
                data-kind={installNotice.kind}
                role={pluginTrustState(plugin) === "blocked" ? "alert" : "note"}
              >
                <strong>{installNotice.title}</strong>
                <span>{installNotice.body}</span>
              </div>
            ) : null}
            {officialPackage ? (
              <dl className="plugin-market-package-grid">
                <div>
                  <dt>来源</dt>
                  <dd>{plugin.packageSource?.toUpperCase() || "R2"}</dd>
                </div>
                <div>
                  <dt>大小</dt>
                  <dd>{formatBytes(plugin.packageSize ?? plugin.size) || "-"}</dd>
                </div>
                <div>
                  <dt>SHA256</dt>
                  <dd title={plugin.packageSha256 || plugin.sha256 || ""}>
                    {compactSha(plugin.packageSha256 || plugin.sha256) || "-"}
                  </dd>
                </div>
                <div>
                  <dt>更新日期</dt>
                  <dd>{plugin.updatedAt ? plugin.updatedAt.slice(0, 10) : "-"}</dd>
                </div>
              </dl>
            ) : (
              <>
                <p className="inline-status">{t("plugin.appUpdate.repo", { repo: plugin.repo ?? "-" })}</p>
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
              </>
            )}
          </div>
        ) : null}
        <TaskProgress task={installTask} />
      </div>
    </Dialog>
  );
}

export function PluginCatalogPanel({
  appUpdateMutation,
  appUpdateTask,
  catalogQuery,
  getCatalogInstallState,
  installMutation,
  installingSource,
  onOpenCatalogInstall,
}: PluginCatalogPanelProps) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const desktopApp = isTauriDesktop();

  const [pendingAppUpdate, setPendingAppUpdate] = useState(false);
  const [appUpdateRefKind, setAppUpdateRefKind] = useState<AppUpdateRefKind>("latest");
  const [appUpdateTagName, setAppUpdateTagName] = useState("");
  const [desktopUpdateStatus, setDesktopUpdateStatus] = useState<DesktopUpdateDialogStatus>("checking");
  const [desktopUpdate, setDesktopUpdate] = useState<DesktopUpdate | null>(null);
  const [desktopUpdateProgress, setDesktopUpdateProgress] = useState<DesktopUpdateProgress | null>(null);
  const [desktopUpdateError, setDesktopUpdateError] = useState("");
  const catalogMatches = useCallback((plugin: PluginCatalogItem, query: string) => {
    return searchablePluginText([
      plugin.id,
      plugin.name,
      plugin.displayName,
      plugin.repo,
      plugin.entry,
      plugin.author,
      plugin.description,
      plugin.shortDescription,
      plugin.version,
      plugin.updatedAt,
      plugin.tags?.join(" "),
      plugin.downloadUrl,
      plugin.packageUrl,
      plugin.downloaded ? "downloaded installed update" : "not installed",
    ]).includes(query);
  }, []);
  const catalogItems = usePagedPluginList({
    items: catalogQuery.data ?? [],
    matcher: catalogMatches,
    pageSize: CATALOG_PAGE_SIZE,
  });

  const appUpdateInfoQuery = useQuery({
    queryFn: getAppUpdateInfo,
    queryKey: ["plugins", "app-update", "info"],
  });
  const appUpdateTagsQuery = useQuery({
    enabled: pendingAppUpdate && !desktopApp,
    queryFn: listAppUpdateTags,
    queryKey: ["plugins", "app-update", "tags"],
    retry: 1,
  });

  useEffect(() => {
    if (!appUpdateTagName && appUpdateTagsQuery.data?.[0]) {
      setAppUpdateTagName(appUpdateTagsQuery.data[0]);
    }
  }, [appUpdateTagName, appUpdateTagsQuery.data]);

  const appUpdateInfo = appUpdateInfoQuery.data;
  const appUpdateDone = !desktopApp && pendingAppUpdate && appUpdateMutation.isSuccess && !appUpdateMutation.isPending;
  const desktopUpdateBusy =
    desktopApp &&
    (desktopUpdateStatus === "checking" ||
      desktopUpdateStatus === "downloading" ||
      desktopUpdateStatus === "installing");

  useEffect(() => {
    if (!desktopApp || !pendingAppUpdate) {
      return;
    }

    let cancelled = false;
    let unlisten: (() => void) | null = null;
    void onDesktopUpdateProgress((progress) => {
      setDesktopUpdateProgress(progress);
      if (progress.event === "started" || progress.event === "progress") {
        setDesktopUpdateStatus("downloading");
      } else if (progress.event === "finished") {
        setDesktopUpdateStatus("installing");
      }
    })
      .then((dispose) => {
        if (cancelled) {
          dispose();
          return;
        }
        unlisten = dispose;
      })
      .catch((error) => {
        if (!cancelled) {
          setDesktopUpdateError(localizedDesktopUpdateError(error, t, "plugin.desktopUpdate.checkFailed"));
          setDesktopUpdateStatus("error");
        }
      });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [desktopApp, pendingAppUpdate, t]);

  const closeAppUpdateDialog = () => {
    if (desktopApp) {
      if (desktopUpdateBusy) {
        return;
      }
      setPendingAppUpdate(false);
      setDesktopUpdateStatus("checking");
      setDesktopUpdate(null);
      setDesktopUpdateProgress(null);
      setDesktopUpdateError("");
      return;
    }
    if (!appUpdateMutation.isPending) {
      appUpdateMutation.reset();
    }
    setPendingAppUpdate(false);
  };

  const openAppUpdateDialog = () => {
    appUpdateMutation.reset();
    setPendingAppUpdate(true);
    if (!desktopApp) {
      return;
    }
    setDesktopUpdateStatus("checking");
    setDesktopUpdate(null);
    setDesktopUpdateProgress(null);
    setDesktopUpdateError("");
    void checkDesktopUpdate()
      .then((update) => {
        setDesktopUpdate(update);
        setDesktopUpdateStatus(update ? "available" : "noUpdate");
      })
      .catch((error) => {
        setDesktopUpdateError(localizedDesktopUpdateError(error, t, "plugin.desktopUpdate.checkFailed"));
        setDesktopUpdateStatus("error");
      });
  };

  const startDesktopUpdateInstall = async () => {
    setDesktopUpdateStatus("downloading");
    setDesktopUpdateError("");
    setDesktopUpdateProgress({ contentLength: null, downloaded: 0, event: "started" });
    try {
      await installDesktopUpdate();
      setDesktopUpdateStatus("restartRequired");
    } catch (error) {
      const message = localizedDesktopUpdateError(error, t, "plugin.desktopUpdate.installFailed");
      setDesktopUpdateError(message);
      setDesktopUpdateStatus("error");
      showToast({
        kind: "error",
        message,
        title: t("plugin.desktopUpdate.title"),
      });
    }
  };
  const desktopUpdateBusyLabel =
    desktopUpdateStatus === "checking"
      ? t("plugin.desktopUpdate.checking")
      : desktopUpdateStatus === "installing"
        ? t("plugin.desktopUpdate.installing")
        : t("plugin.desktopUpdate.downloading");

  const renderCatalogCard = (plugin: PluginCatalogItem) => {
    const source = catalogInstallSource(plugin);
    const url = plugin.sourceUrl || githubUrl(plugin.repo);
    const actionDisabled = !source || installMutation.isPending;
    const displayName = catalogDisplayName(plugin);
    const packageSize = formatBytes(plugin.packageSize ?? plugin.size);
    const tags = catalogTags(plugin).slice(0, 4);
    const officialPackage = hasOfficialPackage(plugin);
    const installState = getCatalogInstallState(plugin);
    const installed = installState.installed || installState.downloaded;
    const updateAvailable = installed && installState.updateAvailable;
    const installActionDisabled = installed && !updateAvailable;
    const actionLabel = updateAvailable
      ? t("plugin.action.update")
      : installed
        ? installState.installed
          ? t("plugin.status.installed")
          : t("plugin.status.downloaded")
        : t("plugin.action.install");
    const pluginForInstallDialog = {
      ...plugin,
      downloaded: installState.downloaded,
      installed: installState.installed,
    };
    const scanPassed = securityScanPassed(plugin);

    return (
      <article className="plugin-market-card" key={catalogKey(plugin)}>
        <div className="plugin-market-card__header">
          <div className="plugin-market-card__logo" aria-hidden="true">
            {plugin.logo ? (
              <img alt="" src={plugin.logo} />
            ) : (
              <img alt="" className="plugin-default-logo" src={defaultPluginLogoUrl} />
            )}
          </div>
          <div className="plugin-market-card__identity">
            <div className="plugin-market-card__title-row">
              <h3 title={displayName}>{displayName}</h3>
              <CatalogTrustBadge plugin={plugin} />
            </div>
            <span className="plugin-market-card__id" title={plugin.name}>
              {plugin.name}
            </span>
            <div className="plugin-market-card__version-row">
              {plugin.version ? <span className="plugin-card__badge">v{plugin.version.replace(/^v/i, "")}</span> : null}
              {plugin.lowestShinsekaiVersion ? (
                <span className="plugin-card__badge plugin-card__badge--support">
                  支持 {plugin.lowestShinsekaiVersion}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <p className="plugin-market-card__description">{catalogDescription(plugin) || plugin.repo || plugin.entry}</p>

        <div className="plugin-market-card__badges" aria-label="插件元数据">
          {officialPackage ? (
            <span className="plugin-market-badge plugin-market-badge--official">
              <PackageCheck aria-hidden size={13} />
              {plugin.packageSource?.toUpperCase() || "R2"}
            </span>
          ) : (
            <span className="plugin-market-badge">
              <GitBranch aria-hidden size={13} />
              GitHub
            </span>
          )}
          {scanPassed ? (
            <span className="plugin-market-badge plugin-market-badge--safe">
              <ShieldCheck aria-hidden size={13} />
              扫描通过
            </span>
          ) : null}
          {installed ? (
            <span className="plugin-market-badge plugin-market-badge--installed">
              <CheckCircle2 aria-hidden size={13} />
              {plugin.downloaded ? t("plugin.status.downloaded") : t("plugin.status.installed")}
            </span>
          ) : null}
        </div>

        <div className="plugin-market-card__meta">
          {catalogAuthorLink(plugin) ? (
            <button
              className="plugin-inline-link"
              onClick={() => openExternal(catalogAuthorLink(plugin))}
              title={catalogAuthorLink(plugin)}
              type="button"
            >
              <UserRound aria-hidden size={14} />
              {plugin.author || "-"}
            </button>
          ) : (
            <span title={plugin.author || ""}>
              <UserRound aria-hidden size={14} />
              {plugin.author || "-"}
            </span>
          )}
          <span title={plugin.updatedAt || ""}>
            <Clock3 aria-hidden size={14} />
            {plugin.updatedAt ? plugin.updatedAt.slice(0, 10) : "-"}
          </span>
          <span>
            <Star aria-hidden size={14} />
            {Number(plugin.stars || 0).toLocaleString()}
          </span>
          {packageSize ? (
            <span title={plugin.packageR2Key || plugin.downloadUrl || ""}>
              <Box aria-hidden size={14} />
              {packageSize}
            </span>
          ) : null}
        </div>

        <div className="plugin-market-card__tags">
          {tags.map((tag) => (
            <span className="plugin-market-chip" key={tag}>
              <Tag aria-hidden size={12} />
              {tag}
            </span>
          ))}
          {catalogTags(plugin).length > tags.length ? (
            <span className="plugin-market-chip plugin-market-chip--muted">
              +{catalogTags(plugin).length - tags.length}
            </span>
          ) : null}
        </div>

        <div className="plugin-market-card__foot">
          <span className="plugin-market-card__source" title={plugin.repo || plugin.entry || ""}>
            {officialPackage
              ? compactSha(plugin.packageSha256 || plugin.sha256) || "官方包体"
              : plugin.repo || plugin.entry}
          </span>
          <div className="inline-actions">
            <AsyncButton
              disabled={actionDisabled || installActionDisabled}
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              loading={installMutation.isPending && installingSource === source}
              onClick={() => {
                if (installActionDisabled) {
                  return;
                }
                if (plugin.repo || officialPackage) {
                  onOpenCatalogInstall(pluginForInstallDialog);
                  return;
                }
                installMutation.mutate(source);
              }}
              variant="primary"
            >
              {actionLabel}
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
        </div>
      </article>
    );
  };

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
            onClick={openAppUpdateDialog}
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
        <PluginListControls
          filteredCount={catalogItems.filteredItems.length}
          page={catalogItems.page}
          placeholder={t("plugin.list.searchCatalog")}
          query={catalogItems.query}
          setPage={catalogItems.setPage}
          setQuery={catalogItems.setQuery}
          totalCount={catalogItems.totalItems}
          totalPages={catalogItems.totalPages}
        />
      ) : null}
      {catalogItems.pagedItems.length ? (
        <div className="plugin-market-grid">{catalogItems.pagedItems.map(renderCatalogCard)}</div>
      ) : null}
      {!catalogQuery.isLoading &&
      !catalogQuery.isError &&
      catalogQuery.data?.length &&
      !catalogItems.filteredItems.length ? (
        <EmptyState title={t("plugin.list.noMatches")} />
      ) : null}
      {!catalogQuery.isLoading && !catalogQuery.isError && !catalogQuery.data?.length ? (
        <EmptyState title={t("plugin.catalog.emptyTitle")} body={t("plugin.catalog.emptyBody")} />
      ) : null}

      {/* App update dialog */}
      <Dialog
        closeLabel={t("common.close")}
        footer={
          desktopApp ? (
            desktopUpdateStatus === "available" ? (
              <>
                <Button onClick={closeAppUpdateDialog}>{t("common.cancel")}</Button>
                <AsyncButton
                  icon={<DownloadCloud aria-hidden className="button__icon" />}
                  onClick={() => void startDesktopUpdateInstall()}
                  variant="primary"
                >
                  {t("plugin.desktopUpdate.installRestart")}
                </AsyncButton>
              </>
            ) : desktopUpdateBusy ? (
              <Button disabled>{desktopUpdateBusyLabel}</Button>
            ) : (
              <Button onClick={closeAppUpdateDialog} variant="primary">
                {t("common.confirm")}
              </Button>
            )
          ) : appUpdateDone ? (
            <Button onClick={closeAppUpdateDialog} variant="primary">
              {t("common.confirm")}
            </Button>
          ) : (
            <>
              <Button onClick={closeAppUpdateDialog}>{t("common.cancel")}</Button>
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
                  appUpdateMutation.mutate({ refKind: appUpdateRefKind, tagName: appUpdateTagName });
                }}
                variant="danger"
              >
                {t("plugin.appUpdate.confirm")}
              </AsyncButton>
            </>
          )
        }
        onClose={closeAppUpdateDialog}
        open={pendingAppUpdate}
        title={desktopApp ? t("plugin.desktopUpdate.title") : t("plugin.appUpdate.title")}
      >
        {desktopApp ? (
          <div className="plugin-detail desktop-update-detail">
            {desktopUpdateStatus === "checking" ? (
              <p className="inline-status">{t("plugin.desktopUpdate.checking")}</p>
            ) : null}
            {desktopUpdateStatus === "noUpdate" ? (
              <p className="plugin-card__description">{t("plugin.desktopUpdate.noUpdate")}</p>
            ) : null}
            {desktopUpdate ? (
              <div className="desktop-update-summary">
                <strong>{t("plugin.desktopUpdate.available", { version: desktopUpdate.version })}</strong>
                {desktopUpdate.date ? (
                  <span className="inline-status">
                    {t("plugin.desktopUpdate.releaseDate", { date: desktopUpdate.date })}
                  </span>
                ) : null}
                {desktopUpdate.body ? (
                  <div className="desktop-update-notes">
                    <span className="field-row__label">{t("plugin.desktopUpdate.releaseNotes")}</span>
                    <p>{desktopUpdate.body}</p>
                  </div>
                ) : null}
              </div>
            ) : null}
            {desktopUpdateStatus === "downloading" || desktopUpdateStatus === "installing" ? (
              <DesktopUpdateProgressView
                label={
                  desktopUpdateStatus === "installing"
                    ? t("plugin.desktopUpdate.installing")
                    : t("plugin.desktopUpdate.downloading")
                }
                progress={desktopUpdateProgress}
                unknownSizeLabel={t("plugin.desktopUpdate.unknownSize")}
              />
            ) : null}
            {desktopUpdateStatus === "restartRequired" ? (
              <p className="plugin-card__description">{t("plugin.desktopUpdate.restartRequiredBody")}</p>
            ) : null}
            {desktopUpdateStatus === "error" ? (
              <p className="field-row__help" role="alert">
                {desktopUpdateError || t("plugin.appUpdate.failed")}
              </p>
            ) : null}
          </div>
        ) : (
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
        )}
      </Dialog>
    </section>
  );
}

function DesktopUpdateProgressView({
  label,
  progress,
  unknownSizeLabel,
}: {
  label: string;
  progress: DesktopUpdateProgress | null;
  unknownSizeLabel: string;
}) {
  const percent = desktopUpdateProgressPercent(progress);
  const detail = desktopUpdateProgressLabel(progress, unknownSizeLabel);
  return (
    <div className="desktop-update-progress">
      <div className="desktop-update-progress__header">
        <span>{label}</span>
        <span>{percent == null ? "" : `${percent}%`}</span>
      </div>
      <div
        aria-label={label}
        aria-valuemax={percent == null ? undefined : 100}
        aria-valuemin={percent == null ? undefined : 0}
        aria-valuenow={percent ?? undefined}
        className="desktop-update-progress__track"
        role="progressbar"
      >
        <span
          className="desktop-update-progress__bar"
          style={{ width: `${percent ?? 100}%` }}
          data-indeterminate={percent == null || undefined}
        />
      </div>
      {detail ? <span className="inline-status">{detail}</span> : null}
    </div>
  );
}

function desktopUpdateProgressPercent(progress: DesktopUpdateProgress | null) {
  const contentLength = progress?.contentLength ?? 0;
  if (!progress || contentLength <= 0) {
    return null;
  }
  return Math.min(100, Math.max(0, Math.round((progress.downloaded / contentLength) * 100)));
}

function desktopUpdateProgressLabel(progress: DesktopUpdateProgress | null, unknownSizeLabel: string) {
  if (!progress) {
    return "";
  }
  const downloaded = formatUpdateBytes(progress.downloaded);
  if (!progress.contentLength || progress.contentLength <= 0) {
    return `${downloaded} / ${unknownSizeLabel}`;
  }
  return `${downloaded} / ${formatUpdateBytes(progress.contentLength)}`;
}

function formatUpdateBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"] as const;
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`;
}

function localizedDesktopUpdateError(error: unknown, t: I18nT, fallbackKey: DesktopUpdateErrorFallback) {
  const rawMessage = desktopRestartErrorMessage(error).trim();
  if (!rawMessage) {
    return t(fallbackKey);
  }
  if (rawMessage.toLowerCase().includes("no pending desktop update")) {
    return t("plugin.desktopUpdate.errorNoPending");
  }
  return t("plugin.desktopUpdate.errorWithDetail", {
    message: rawMessage,
    prefix: t(fallbackKey),
  });
}
