import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { DownloadCloud, ExternalLink, RefreshCw } from "lucide-react";

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
  appUpdateMutation: ReturnType<
    typeof useMutation<AppUpdateResult, Error, { refKind: AppUpdateRefKind; tagName: string }>
  >;
  catalogQuery: ReturnType<typeof useQuery<PluginCatalogItem[]>>;
  installMutation: ReturnType<typeof useMutation<PluginManifest, Error, string | PluginInstallInput>>;
  installTask: TaskSnapshot<PluginManifest> | null;
  installingSource: string;
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

export function PluginCatalogPanel({
  appUpdateMutation,
  catalogQuery,
  installMutation,
  installTask,
  installingSource,
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
  const [pendingCatalogInstall, setPendingCatalogInstall] = useState<PluginCatalogItem | null>(null);
  const [catalogRefKind, setCatalogRefKind] = useState<AppUpdateRefKind>("latest");
  const [catalogTagName, setCatalogTagName] = useState("");

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
  const catalogTagsQuery = useQuery({
    enabled: Boolean(pendingCatalogInstall?.repo),
    queryFn: () => listRepoTags(pendingCatalogInstall ? catalogInstallSource(pendingCatalogInstall) : ""),
    queryKey: ["plugins", "repo-tags", pendingCatalogInstall ? catalogInstallSource(pendingCatalogInstall) : ""],
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
  const catalogInstallDone = Boolean(pendingCatalogInstall && installMutation.isSuccess && !installMutation.isPending);
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

  const closeCatalogInstallDialog = () => {
    if (!installMutation.isPending) {
      installMutation.reset();
    }
    setPendingCatalogInstall(null);
  };

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

  const catalogColumns = [
    {
      header: t("plugin.plugin"),
      key: "name",
      render: (plugin: PluginCatalogItem) => (
        <div className="plugin-catalog-identity">
          <strong className="plugin-catalog-identity__name" title={plugin.name}>
            {plugin.name}
          </strong>
          {plugin.repo ? (
            <span className="plugin-catalog-identity__repo" title={plugin.repo}>
              {plugin.repo}
            </span>
          ) : null}
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
                  installMutation.reset();
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
          catalogInstallDone ? (
            <Button onClick={closeCatalogInstallDialog} variant="primary">
              {t("common.confirm")}
            </Button>
          ) : (
            <>
              <Button onClick={closeCatalogInstallDialog}>{t("common.cancel")}</Button>
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
          )
        }
        onClose={closeCatalogInstallDialog}
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
          <TaskProgress task={installTask} />
        </div>
      </Dialog>

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
