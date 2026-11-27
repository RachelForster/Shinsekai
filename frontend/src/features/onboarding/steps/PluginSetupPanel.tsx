import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, DownloadCloud, Globe2, Heart, Settings, Smartphone } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { installMissingRuntimeDependency } from "../../../entities/chat/repository";
import {
  installPlugin,
  listPlugins,
  listPluginCatalog,
  pluginCatalogQueryKey,
  pluginsQueryKey,
} from "../../../entities/plugin/repository";
import type { PluginCatalogItem, PluginManifest } from "../../../entities/plugin/types";
import {
  desktopRestartErrorMessage,
  isTauriDesktop,
  writeDesktopRestartDebugLog,
} from "../../../shared/desktop/desktopApi";
import { useI18n } from "../../../shared/i18n";
import type { RuntimeDependencyInstallResult, TaskSnapshot } from "../../../shared/platform/types";
import { Button, EmptyState, QueryErrorState, TaskProgress, useToast } from "../../../shared/ui";
import { catalogInstallSource } from "../../plugin-manager/pluginUtils";
import { reloadPluginService } from "../../plugin-manager/pluginReload";
import { OnboardingPanelLayout, OnboardingTaskPanel } from "../OnboardingPanelLayout";

type PluginPresetId = "heartbeat" | "chatPhone" | "browser";

interface PluginPreset {
  body: string;
  dependencies: string[];
  excludedKeywords?: string[];
  guide: string;
  id: PluginPresetId;
  keywords: string[];
  title: string;
}

interface PluginSetupPanelProps {
  onInstalled?: () => void;
}

type PluginReloadStatus = "idle" | "reloading" | "done" | "failed";

function splitKeywords(csv: string): string[] {
  return csv
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeSearchText(value: string) {
  return value.toLowerCase().replace(/[_-]+/g, " ");
}

function pluginSearchText(plugin: PluginCatalogItem) {
  return normalizeSearchText(
    [
      plugin.id,
      plugin.name,
      plugin.displayName,
      plugin.description,
      plugin.shortDescription,
      plugin.entry,
      plugin.repo,
      ...(plugin.tags ?? []),
    ]
      .filter(Boolean)
      .join(" "),
  );
}

function pluginIdentityText(plugin: PluginCatalogItem) {
  return normalizeSearchText(
    [plugin.id, plugin.name, plugin.displayName, plugin.entry, plugin.repo, ...(plugin.tags ?? [])]
      .filter(Boolean)
      .join(" "),
  );
}

function pluginTitle(plugin: PluginCatalogItem) {
  const raw = plugin as PluginCatalogItem & { display_name?: string; title?: string };
  return plugin.displayName || raw.display_name || raw.title || plugin.name || plugin.id || plugin.entry;
}

function pluginMatchScore(plugin: PluginCatalogItem, preset: PluginPreset) {
  const identity = pluginIdentityText(plugin);
  const text = pluginSearchText(plugin);
  if (preset.excludedKeywords?.some((keyword) => text.includes(normalizeSearchText(keyword)))) {
    return 0;
  }
  return preset.keywords.reduce((score, keyword) => {
    const normalized = normalizeSearchText(keyword);
    if (identity.includes(normalized)) {
      return score + 3;
    }
    if (text.includes(normalized)) {
      return score + 1;
    }
    return score;
  }, 0);
}

function findPluginMatch(catalog: PluginCatalogItem[], preset: PluginPreset) {
  let best: { plugin: PluginCatalogItem; score: number } | null = null;
  for (const plugin of catalog) {
    const score = pluginMatchScore(plugin, preset);
    if (score > 0 && (!best || score > best.score)) {
      best = { plugin, score };
    }
  }
  return best?.plugin;
}

function pluginHasConfig(plugin: PluginManifest | null | undefined) {
  return Boolean(plugin && ((plugin.settingsPages ?? []).length || (plugin.toolsTabs ?? []).length));
}

function findReloadedPlugin(plugin: PluginManifest, plugins: PluginManifest[]) {
  return (
    plugins.find((item) => item.id === plugin.id) ??
    plugins.find((item) => item.entry && item.entry === plugin.entry) ??
    plugins.find((item) => item.title && item.title === plugin.title)
  );
}

function pluginManifestText(plugin: PluginManifest) {
  return normalizeSearchText(
    [
      plugin.id,
      plugin.title,
      plugin.description,
      plugin.entry,
      plugin.directory,
      plugin.install?.entry,
      plugin.install?.repo,
      plugin.install?.sourceLabel,
      ...(plugin.settingsPages ?? []),
      ...(plugin.toolsTabs ?? []),
      ...(plugin.slots ?? []),
    ]
      .filter(Boolean)
      .join(" "),
  );
}

function installedPluginMatchScore(plugin: PluginManifest, preset: PluginPreset) {
  const text = pluginManifestText(plugin);
  if (preset.excludedKeywords?.some((keyword) => text.includes(normalizeSearchText(keyword)))) {
    return 0;
  }
  return preset.keywords.reduce((score, keyword) => {
    return text.includes(normalizeSearchText(keyword)) ? score + 1 : score;
  }, 0);
}

function findInstalledPresetPlugin(plugins: PluginManifest[], preset: PluginPreset) {
  let best: { plugin: PluginManifest; score: number } | null = null;
  for (const plugin of plugins) {
    const score = installedPluginMatchScore(plugin, preset);
    if (score > 0 && (!best || score > best.score)) {
      best = { plugin, score };
    }
  }
  return best?.plugin;
}

export function PluginSetupPanel({ onInstalled }: PluginSetupPanelProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [selectedIds, setSelectedIds] = useState<PluginPresetId[]>(["heartbeat", "chatPhone", "browser"]);
  const [dependencyTask, setDependencyTask] = useState<TaskSnapshot<RuntimeDependencyInstallResult> | null>(null);
  const [installTask, setInstallTask] = useState<TaskSnapshot<PluginManifest> | null>(null);
  const [installedPlugins, setInstalledPlugins] = useState<Partial<Record<PluginPresetId, PluginManifest>>>({});
  const [reloadError, setReloadError] = useState("");
  const [reloadStatus, setReloadStatus] = useState<PluginReloadStatus>("idle");
  const catalogQuery = useQuery({
    queryFn: listPluginCatalog,
    queryKey: pluginCatalogQueryKey,
    staleTime: 300_000,
  });
  const pluginsQuery = useQuery({
    queryFn: listPlugins,
    queryKey: pluginsQueryKey,
    staleTime: 30_000,
  });

  const presets = useMemo<PluginPreset[]>(
    () => [
      {
        body: t("onboarding.plugins.heartbeatBody"),
        dependencies: [],
        excludedKeywords: ["browser", "playwright", "chat_phone", "doki"],
        guide: t("onboarding.plugins.heartbeatGuide"),
        id: "heartbeat",
        keywords: splitKeywords(t("onboarding.plugins.keywords.heartbeat")),
        title: t("onboarding.plugins.heartbeatTitle"),
      },
      {
        body: t("onboarding.plugins.chatPhoneBody"),
        dependencies: [],
        excludedKeywords: ["browser", "playwright", "heartbeat"],
        guide: t("onboarding.plugins.chatPhoneGuide"),
        id: "chatPhone",
        keywords: splitKeywords(t("onboarding.plugins.keywords.chatPhone")),
        title: t("onboarding.plugins.chatPhoneTitle"),
      },
      {
        body: t("onboarding.plugins.browserBody"),
        dependencies: ["playwright"],
        excludedKeywords: splitKeywords(t("onboarding.plugins.keywords.voiceExclude")),
        guide: t("onboarding.plugins.browserGuide"),
        id: "browser",
        keywords: splitKeywords(t("onboarding.plugins.keywords.browser")),
        title: t("onboarding.plugins.browserTitle"),
      },
    ],
    [t],
  );
  const catalog = catalogQuery.data ?? [];
  const selectedPresets = presets.filter((preset) => selectedIds.includes(preset.id));

  const installMutation = useMutation({
    mutationFn: async () => {
      const installed: Partial<Record<PluginPresetId, PluginManifest>> = {};
      const modules = Array.from(new Set(selectedPresets.flatMap((preset) => preset.dependencies)));
      for (const moduleName of modules) {
        await installMissingRuntimeDependency({ moduleName }, { onTaskUpdate: setDependencyTask });
      }
      for (const preset of selectedPresets) {
        const plugin = findPluginMatch(catalog, preset);
        const source = plugin ? catalogInstallSource(plugin) : "";
        if (!source) {
          continue;
        }
        installed[preset.id] = await installPlugin(source, { onTaskUpdate: setInstallTask });
      }
      if (Object.keys(installed).length) {
        setInstalledPlugins(installed);
        if (isTauriDesktop()) {
          setReloadStatus("reloading");
          try {
            await reloadPluginService(queryClient);
          } catch (error) {
            const message = desktopRestartErrorMessage(error);
            setReloadStatus("failed");
            setReloadError(message);
            await writeDesktopRestartDebugLog(`Onboarding plugin reload catch: ${message}`);
            throw error;
          }
          setReloadStatus("done");
        }
        const reloadedPlugins = await queryClient.fetchQuery({ queryFn: listPlugins, queryKey: pluginsQueryKey });
        const refreshed = Object.fromEntries(
          Object.entries(installed).map(([presetId, plugin]) => [
            presetId,
            findReloadedPlugin(plugin, reloadedPlugins) ?? plugin,
          ]),
        ) as Partial<Record<PluginPresetId, PluginManifest>>;
        setInstalledPlugins(refreshed);
      }
    },
    onMutate() {
      setDependencyTask(null);
      setInstallTask(null);
      setInstalledPlugins({});
      setReloadError("");
      setReloadStatus("idle");
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("onboarding.toastFailed"),
      });
    },
    onSuccess() {
      showToast({ kind: "success", title: t("onboarding.plugins.installDone") });
      onInstalled?.();
      void queryClient.invalidateQueries({ queryKey: pluginsQueryKey });
      void queryClient.invalidateQueries({ queryKey: pluginCatalogQueryKey });
    },
  });

  const toggleSelected = (id: PluginPresetId) => {
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };

  let content;
  if (catalogQuery.isLoading) {
    content = <EmptyState title={t("onboarding.plugins.loading")} />;
  } else if (catalogQuery.isError) {
    content = (
      <QueryErrorState
        error={catalogQuery.error}
        onRetry={() => void catalogQuery.refetch()}
        retryLabel={t("onboarding.actions.retry")}
        title={t("onboarding.toastFailed")}
      />
    );
  } else {
    content = (
      <div className="onboarding-plugin-stack">
        <div className="onboarding-plugin-dependency-note">{t("onboarding.plugins.marketplaceHint")}</div>
        <div className="onboarding-plugin-choice-grid">
          {presets.map((preset) => {
            const plugin = findPluginMatch(catalog, preset);
            const selected = selectedIds.includes(preset.id);
            const Icon = preset.id === "heartbeat" ? Heart : preset.id === "chatPhone" ? Smartphone : Globe2;
            const installedPlugin =
              installedPlugins[preset.id] ?? findInstalledPresetPlugin(pluginsQuery.data ?? [], preset);
            const hasConfig = pluginHasConfig(installedPlugin);
            const canConfigure = Boolean(
              installedPlugin && hasConfig && (reloadStatus === "done" || installedPlugin.loaded !== false),
            );
            const status = installedPlugin
              ? hasConfig
                ? t("onboarding.plugins.configReady")
                : t("onboarding.plugins.installedNoConfig")
              : plugin
                ? pluginTitle(plugin)
                : t("onboarding.plugins.noMatch");
            return (
              <article
                className="onboarding-plugin-choice"
                data-selected={selected ? "true" : undefined}
                data-installed={installedPlugin ? "true" : undefined}
                key={preset.id}
              >
                <button
                  className="onboarding-plugin-choice__select"
                  disabled={installMutation.isPending}
                  onClick={() => toggleSelected(preset.id)}
                  type="button"
                >
                  <span className="onboarding-plugin-choice__mark">
                    {installedPlugin || selected ? (
                      <CheckCircle2 aria-hidden size={18} />
                    ) : (
                      <Icon aria-hidden size={18} />
                    )}
                  </span>
                  <span className="onboarding-plugin-choice__body">
                    <strong>{preset.title}</strong>
                    <span>{preset.body}</span>
                    <em>{status}</em>
                    <small>{preset.guide}</small>
                  </span>
                </button>
                {installedPlugin && canConfigure ? (
                  <Button
                    className="onboarding-plugin-choice__configure"
                    icon={<Settings aria-hidden size={15} />}
                    onClick={() =>
                      navigate("/settings/plugins", {
                        state: {
                          pluginId: installedPlugin.id,
                          returnTo: {
                            hash: location.hash,
                            pathname: location.pathname,
                            search: location.search,
                            state: { activeStep: "plugins" },
                          },
                        },
                      })
                    }
                    variant="ghost"
                  >
                    {t("onboarding.plugins.configure")}
                  </Button>
                ) : null}
              </article>
            );
          })}
        </div>
        <div className="onboarding-plugin-install-bar">
          <span>{t("onboarding.plugins.selectedCount", { count: selectedPresets.length })}</span>
          <Button
            disabled={!selectedPresets.length || installMutation.isPending}
            icon={<DownloadCloud aria-hidden size={16} />}
            loading={installMutation.isPending}
            onClick={() => installMutation.mutate()}
            variant="primary"
          >
            {t("onboarding.plugins.installSelected")}
          </Button>
        </div>
        {installMutation.isPending || reloadStatus !== "idle" ? (
          <div className="onboarding-plugin-install-status" data-state={reloadStatus}>
            {reloadStatus === "reloading"
              ? t("onboarding.plugins.reloadPending")
              : reloadStatus === "done"
                ? t("onboarding.plugins.installDone")
                : reloadStatus === "failed"
                  ? reloadError
                    ? t("onboarding.plugins.reloadFailedDetail", { detail: reloadError })
                    : t("onboarding.plugins.reloadFailed")
                  : t("onboarding.plugins.installPending")}
          </div>
        ) : null}
        <TaskProgress task={dependencyTask} />
        <TaskProgress task={installTask} />
      </div>
    );
  }

  return (
    <OnboardingPanelLayout description={t("onboarding.plugins.description")} title={t("onboarding.plugins.title")}>
      <OnboardingTaskPanel
        defaultOpen
        description={t("onboarding.plugins.dependencyStep")}
        title={t("onboarding.plugins.title")}
      >
        {content}
      </OnboardingTaskPanel>
    </OnboardingPanelLayout>
  );
}
