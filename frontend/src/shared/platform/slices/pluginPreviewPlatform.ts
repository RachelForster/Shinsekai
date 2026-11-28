import { translateRuntimeMessage } from "../../i18n/runtimeLanguage";
import { sampleMcpConfig, sampleMcpTools, samplePluginCatalog, samplePlugins } from "../sampleData";
import type {
  McpPlatform,
  PluginCatalogItem,
  PluginManifest,
  PluginsPlatform,
  PluginSubmissionInput,
  PluginUIPage,
} from "./pluginTypes";
import { clone, delay, previewTask } from "./previewContext";

const PREVIEW_PLUGIN_SUBMIT_URL =
  "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new?template=PLUGIN_PUBLISH.yml";

function previewNormalizePluginKey(value: string | null | undefined) {
  return (value ?? "")
    .trim()
    .toLowerCase()
    .replace(/^git@github\.com:/i, "")
    .replace(/^https?:\/\/github\.com\//i, "")
    .replace(/^github\.com\//i, "")
    .replace(/\.git$/i, "")
    .replace(/[^\p{L}\p{N}]+/gu, "_")
    .replace(/^_+|_+$/g, "");
}

function previewModuleToken(value: string | null | undefined) {
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

function previewPluginDirectory(entry: string, fallback: string) {
  const token = previewModuleToken(entry) || previewNormalizePluginKey(fallback) || "preview";
  return `plugins/${token.replace(/[^A-Za-z0-9_\u3040-\u30ff\u3400-\u9fff]+/g, "_")}`;
}

function previewCatalogKeys(plugin: PluginCatalogItem) {
  return new Set(
    [plugin.id, plugin.name, plugin.repo, plugin.entry, previewModuleToken(plugin.entry)]
      .map(previewNormalizePluginKey)
      .filter((key) => key.length >= 2),
  );
}

function previewManifestKeys(plugin: PluginManifest) {
  return new Set(
    [
      plugin.id,
      plugin.entry,
      plugin.directory?.split(/[\\/]/).filter(Boolean).at(-1),
      plugin.install?.repo,
      plugin.install?.entry,
      previewModuleToken(plugin.entry),
    ]
      .map(previewNormalizePluginKey)
      .filter((key) => key.length >= 2),
  );
}

function previewCatalogForSource(source: string, catalogItems: PluginCatalogItem[]) {
  const sourceKey = previewNormalizePluginKey(source);
  const rawLower = source.trim().toLowerCase();
  return catalogItems.find(
    (item) =>
      previewCatalogKeys(item).has(sourceKey) ||
      Boolean(rawLower && (item.displayName ?? "").trim().toLowerCase() === rawLower),
  );
}

function previewUpsertPlugin(currentPlugins: PluginManifest[], plugin: PluginManifest, catalog?: PluginCatalogItem) {
  const keys = new Set([...previewManifestKeys(plugin), ...(catalog ? previewCatalogKeys(catalog) : [])]);
  let replaced = false;
  const nextPlugins = currentPlugins.map((item) => {
    for (const key of previewManifestKeys(item)) {
      if (keys.has(key)) {
        replaced = true;
        return plugin;
      }
    }
    return item;
  });
  if (!replaced) {
    return [...nextPlugins, plugin];
  }
  return nextPlugins;
}

function normalizePreviewPluginSubmission(input: PluginSubmissionInput): PluginSubmissionInput {
  const submission: PluginSubmissionInput = {
    author: input.author.trim(),
    desc: input.desc.trim(),
    display_name: input.display_name.trim(),
    repo: input.repo.trim().replace(/\.git$/i, ""),
    social_link: (input.social_link ?? "").trim(),
    tags: (input.tags ?? [])
      .map((tag) => tag.trim())
      .filter(Boolean)
      .slice(0, 5),
  };
  const lowestShinsekaiVersion = (input.lowest_shinsekai_version ?? "").trim();
  if (lowestShinsekaiVersion) {
    submission.lowest_shinsekai_version = lowestShinsekaiVersion;
  }
  return submission;
}

function previewPluginSubmissionErrors(input: PluginSubmissionInput) {
  const submission = normalizePreviewPluginSubmission(input);
  const errors: string[] = [];
  for (const field of ["display_name", "desc", "author", "repo"] as const) {
    if (!submission[field]) {
      errors.push(`${field} is required`);
    }
  }
  if (submission.desc.length > 200) {
    errors.push("desc must be 200 characters or less");
  }
  if (!/^https:\/\/github\.com\/[^/\s]+\/[^/\s]+$/i.test(submission.repo)) {
    errors.push("repo must be a GitHub repository URL");
  }
  if ((input.tags ?? []).filter((tag) => tag.trim()).length > 5) {
    errors.push("tags must contain 5 items or fewer");
  }
  return errors;
}

function previewPluginSubmissionJson(input: PluginSubmissionInput) {
  return JSON.stringify(normalizePreviewPluginSubmission(input), null, 2);
}

function previewPluginIssueUrl(input: PluginSubmissionInput) {
  const submission = normalizePreviewPluginSubmission(input);
  const params = new URLSearchParams({
    "plugin-info": ["```json", previewPluginSubmissionJson(submission), "```", ""].join("\n"),
    template: "PLUGIN_PUBLISH.yml",
    title: `[Plugin] ${submission.display_name}`,
  });
  return `${PREVIEW_PLUGIN_SUBMIT_URL.split("?")[0]}?${params.toString()}`;
}

export function createPluginsPreviewPlatform(): PluginsPlatform {
  let plugins = clone(samplePlugins);
  let pluginCatalog = clone(samplePluginCatalog);

  return {
    async appUpdateRun(input, options) {
      const taskId = `preview-app-update-${Date.now()}`;
      previewTask(
        taskId,
        {
          message: translateRuntimeMessage("plat.preview.plugin.updateDownloading"),
          phase: "download",
          progress: 0.35,
          status: "running",
        },
        options,
      );
      await delay(null, 160);
      previewTask(
        taskId,
        {
          message: translateRuntimeMessage("plat.preview.plugin.updateMerging"),
          phase: "merge",
          progress: 0.72,
          status: "running",
        },
        options,
      );
      await delay(null, 160);
      const target = input.refKind === "tag" ? input.tagName || "tag" : input.refKind;
      const result = {
        message: translateRuntimeMessage("plat.preview.plugin.updateSimulated", { target }),
        pipCode: "app_update_skip_pip",
        version: "preview",
      };
      previewTask(
        taskId,
        { message: result.message, phase: "completed", progress: 1, result, status: "succeeded" },
        options,
      );
      return delay(result);
    },
    appUpdateInfo: () => delay({ repo: "RachelForster/Shinsekai", version: "preview" }),
    appUpdateTags: () => delay(["v1.0.0", "v0.9.0"]),
    catalog: () => delay(pluginCatalog),
    getUi(id) {
      const plugin = plugins.find((item) => item.id === id || item.entry === id);
      if (!plugin) {
        return Promise.reject(new Error(translateRuntimeMessage("plat.preview.plugin.notFound", { id })));
      }
      const settingsPages: PluginUIPage[] = plugin.settingsPages.map((title, index) => ({
        id: `settings-${index}`,
        kind: "settings",
        order: index,
        pluginId: plugin.id,
        pluginVersion: plugin.version,
        title,
        unavailableReason: translateRuntimeMessage("plat.preview.plugin.noSettingsSchema"),
      }));
      const toolsPages: PluginUIPage[] = plugin.toolsTabs.map((title, index) => ({
        id: `tools-${index}`,
        kind: "tools",
        order: index + settingsPages.length,
        pluginId: plugin.id,
        pluginVersion: plugin.version,
        title,
        unavailableReason: translateRuntimeMessage("plat.preview.plugin.noToolsSchema"),
      }));
      return delay({ pages: [...settingsPages, ...toolsPages], plugin });
    },
    async install(input, options) {
      const id = typeof input === "string" ? input : input.source;
      const catalog = previewCatalogForSource(id, pluginCatalog);
      const entry = catalog?.entry || id;
      const title = catalog?.displayName || catalog?.name || id;
      const repo = catalog?.repo || "";
      const packageSha256 = catalog?.packageSha256 || catalog?.sha256 || "";
      const taskId = `preview-${Date.now()}`;
      previewTask(
        taskId,
        {
          message: translateRuntimeMessage("plat.preview.plugin.downloadingManifest"),
          phase: "download",
          progress: 0.25,
          status: "running",
        },
        options,
      );
      await delay(null, 180);
      previewTask(
        taskId,
        {
          message: translateRuntimeMessage("plat.preview.plugin.installingDeps"),
          phase: "pip",
          progress: 0.72,
          status: "running",
        },
        options,
      );
      await delay(null, 220);
      const plugin: PluginManifest = {
        author: catalog?.author || "Preview",
        description: translateRuntimeMessage("plat.preview.plugin.installedDesc"),
        directory: previewPluginDirectory(entry, id),
        enabled: true,
        entry,
        id: catalog?.id || catalog?.name || id,
        install: {
          entry,
          packageSha256,
          packageSize: catalog?.packageSize ?? catalog?.size ?? null,
          packageSource: catalog?.packageSource || (catalog?.packageUrl ? "r2" : ""),
          packageStatus: packageSha256 ? "verified" : "installed",
          packageUrl: catalog?.packageUrl || catalog?.downloadUrl || "",
          repo,
          sourceLabel: catalog?.packageUrl ? "Official package (R2)" : repo ? "GitHub" : "Preview",
          sourceType: catalog?.packageUrl ? "package" : repo ? "github" : "preview",
        },
        loaded: true,
        permissions: ["settings"],
        settingsPages: [translateRuntimeMessage("plat.preview.plugin.settingsPage")],
        slots: ["settings-extension"],
        title,
        toolsTabs: [],
        version: catalog?.version || "preview",
      };
      plugins = previewUpsertPlugin(plugins, plugin, catalog);
      pluginCatalog = pluginCatalog.map((item) =>
        previewCatalogKeys(item).has(previewNormalizePluginKey(id))
          ? { ...item, downloaded: true, installed: true }
          : item,
      );
      previewTask(
        taskId,
        {
          message: translateRuntimeMessage("plat.preview.plugin.installed"),
          phase: "completed",
          progress: 1,
          result: plugin,
          status: "succeeded",
        },
        options,
      );
      return delay(plugin, 400);
    },
    list: () => delay(plugins),
    listSessionBehaviors: () => Promise.resolve([]),
    listSlotContributions: () =>
      delay(
        plugins.some((plugin) => plugin.id === "core-tools" && plugin.enabled)
          ? [
              {
                actionLabel: translateRuntimeMessage("plat.preview.plugin.slotActionLabel"),
                actionType: "callback" as const,
                actionable: true,
                description: translateRuntimeMessage("plat.preview.plugin.slotDesc"),
                icon: "sparkles" as const,
                id: "scene-prompt",
                order: 100,
                pageId: "",
                pluginId: "core-tools",
                pluginVersion: "built-in",
                presentation: "button" as const,
                slot: "chat-output" as const,
                title: translateRuntimeMessage("plat.preview.plugin.slotTitle"),
                variant: "ghost" as const,
              },
            ]
          : [],
      ),
    status: () => delay({ status: "ready" as const }),
    repoTags: () => delay(["v1.0.0", "v0.9.0"]),
    runSlotContribution: (pluginId, contributionId) =>
      delay({
        id: contributionId,
        kind: "success" as const,
        message: translateRuntimeMessage("plat.preview.plugin.slotActionRan"),
        pluginId,
      }),
    scanLocal(input) {
      const baseName = input.path.split(/[\\/]/).filter(Boolean).pop() || "preview-plugin";
      return delay({
        author: "Shinsekai Contributors",
        desc: translateRuntimeMessage("plat.preview.plugin.scanDesc"),
        display_name: baseName.replace(/[-_]+/g, " "),
        entry: `plugins.${baseName.replace(/[^A-Za-z0-9_]/g, "_")}.plugin:PreviewPlugin`,
        logo: "logo.png",
        path: input.path,
        repo: `https://github.com/shinsekai/${baseName}`,
        requirements: "",
        social_link: "https://github.com/shinsekai",
        tags: ["preview"],
        warnings: [translateRuntimeMessage("plat.preview.plugin.scanWarning")],
      });
    },
    validateSubmission(input) {
      const errors = previewPluginSubmissionErrors(input);
      const submission = normalizePreviewPluginSubmission(input);
      return delay({
        errors,
        json: errors.length ? undefined : previewPluginSubmissionJson(submission),
        ok: errors.length === 0,
        submission: errors.length ? undefined : submission,
      });
    },
    buildSubmissionIssueUrl(input) {
      const errors = previewPluginSubmissionErrors(input);
      if (errors.length) {
        return Promise.reject(new Error(errors.join("; ")));
      }
      const submission = normalizePreviewPluginSubmission(input);
      return delay({
        issueUrl: previewPluginIssueUrl(submission),
        json: previewPluginSubmissionJson(submission),
        submission,
        submitUrl: PREVIEW_PLUGIN_SUBMIT_URL,
      });
    },
    copySubmissionJson(input) {
      const errors = previewPluginSubmissionErrors(input);
      if (errors.length) {
        return Promise.reject(new Error(errors.join("; ")));
      }
      const submission = normalizePreviewPluginSubmission(input);
      const json = previewPluginSubmissionJson(submission);
      if (navigator.clipboard?.writeText) {
        void navigator.clipboard.writeText(json);
      }
      return delay({
        clipboardText: json,
        json,
        message: "Preview plugin submission copied.",
        submission,
      });
    },
    runUiAction(id, pageId, actionId, values) {
      const plugin = plugins.find((item) => item.id === id || item.entry === id);
      if (!plugin) {
        return Promise.reject(new Error(translateRuntimeMessage("plat.preview.plugin.notFound", { id })));
      }
      return delay({
        message: translateRuntimeMessage("plat.preview.plugin.actionDone", { action: actionId }),
        page: {
          id: pageId,
          kind: "settings",
          order: 0,
          pluginId: plugin.id,
          pluginVersion: plugin.version,
          schema: [],
          title: pageId,
          values,
        } satisfies PluginUIPage,
        plugin,
        result: {} as Record<string, unknown>,
      });
    },
    saveUiConfig(id, pageId, values) {
      const plugin = plugins.find((item) => item.id === id || item.entry === id);
      if (!plugin) {
        return Promise.reject(new Error(translateRuntimeMessage("plat.preview.plugin.notFound", { id })));
      }
      return delay({
        message: translateRuntimeMessage("plat.preview.plugin.saved"),
        page: {
          id: pageId,
          kind: "settings",
          order: 0,
          pluginId: plugin.id,
          pluginVersion: plugin.version,
          schema: [],
          title: pageId,
          values,
        } satisfies PluginUIPage,
        plugin,
      });
    },
    async setEnabled(id, enabled) {
      plugins = plugins.map((plugin) => (plugin.id === id || plugin.entry === id ? { ...plugin, enabled } : plugin));
      const plugin = plugins.find((item) => item.id === id || item.entry === id);
      if (!plugin) {
        throw new Error(translateRuntimeMessage("plat.preview.plugin.notFound", { id }));
      }
      return delay(plugin);
    },
    async uninstall(id) {
      const plugin = plugins.find((item) => item.id === id || item.entry === id);
      if (!plugin) {
        throw new Error(translateRuntimeMessage("plat.preview.plugin.notFound", { id }));
      }
      plugins = plugins.filter((item) => item.id !== id && item.entry !== id);
      pluginCatalog = pluginCatalog.map((item) =>
        item.entry === id || item.entry === plugin.entry ? { ...item, downloaded: false, installed: false } : item,
      );
      return delay({ message: translateRuntimeMessage("plat.preview.plugin.uninstalled", { title: plugin.title }) });
    },
  };
}

export function createMcpPreviewPlatform(): McpPlatform {
  let mcpConfig = clone(sampleMcpConfig);

  return {
    getConfig: () => delay(mcpConfig),
    openConfigFile: () => delay(mcpConfig.path ?? "data/config/mcp.yaml"),
    async previewTools(_config, options) {
      const taskId = `mcp-preview-${Date.now()}`;
      previewTask(
        taskId,
        {
          kind: "mcp-preview",
          message: translateRuntimeMessage("plat.preview.mcp.probing"),
          phase: "probe",
          progress: 0.4,
          status: "running",
        },
        options,
      );
      await delay(null, 220);
      previewTask(
        taskId,
        {
          kind: "mcp-preview",
          message: translateRuntimeMessage("plat.preview.mcp.refreshed"),
          phase: "completed",
          progress: 1,
          result: sampleMcpTools,
          status: "succeeded",
        },
        options,
      );
      return delay(sampleMcpTools);
    },
    async saveAndApply(nextConfig, options) {
      const taskId = `mcp-apply-${Date.now()}`;
      previewTask(
        taskId,
        {
          kind: "mcp-apply",
          message: translateRuntimeMessage("plat.preview.mcp.writing"),
          phase: "write",
          progress: 0.45,
          status: "running",
        },
        options,
      );
      await delay(null, 180);
      mcpConfig = clone({ ...nextConfig, path: nextConfig.path ?? mcpConfig.path });
      previewTask(
        taskId,
        {
          kind: "mcp-apply",
          message: translateRuntimeMessage("plat.preview.mcp.applied"),
          phase: "completed",
          progress: 1,
          result: mcpConfig,
          status: "succeeded",
        },
        options,
      );
      return delay(mcpConfig);
    },
  };
}
