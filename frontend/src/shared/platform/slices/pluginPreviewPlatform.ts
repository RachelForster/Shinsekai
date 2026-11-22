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
    .replace(/\.git$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
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
  return `plugins/${token.replace(/[^A-Za-z0-9_]+/g, "_")}`;
}

function previewCatalogKeys(plugin: PluginCatalogItem) {
  return new Set(
    [plugin.id, plugin.name, plugin.displayName, plugin.repo, plugin.entry, previewModuleToken(plugin.entry)]
      .map(previewNormalizePluginKey)
      .filter(Boolean),
  );
}

function previewManifestKeys(plugin: PluginManifest) {
  return new Set(
    [
      plugin.id,
      plugin.title,
      plugin.entry,
      plugin.directory?.split(/[\\/]/).filter(Boolean).at(-1),
      plugin.install?.repo,
      plugin.install?.entry,
      previewModuleToken(plugin.entry),
    ]
      .map(previewNormalizePluginKey)
      .filter(Boolean),
  );
}

function previewCatalogForSource(source: string, catalogItems: PluginCatalogItem[]) {
  const sourceKey = previewNormalizePluginKey(source);
  return catalogItems.find((item) => previewCatalogKeys(item).has(sourceKey));
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
        { message: "正在下载源码归档。", phase: "download", progress: 0.35, status: "running" },
        options,
      );
      await delay(null, 160);
      previewTask(
        taskId,
        { message: "正在合并到程序目录。", phase: "merge", progress: 0.72, status: "running" },
        options,
      );
      await delay(null, 160);
      const result = {
        message: `已模拟更新到 ${input.refKind === "tag" ? input.tagName || "tag" : input.refKind}。`,
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
        return Promise.reject(new Error(`插件不存在：${id}`));
      }
      const settingsPages: PluginUIPage[] = plugin.settingsPages.map((title, index) => ({
        id: `settings-${index}`,
        kind: "settings",
        order: index,
        pluginId: plugin.id,
        pluginVersion: plugin.version,
        title,
        unavailableReason: "浏览器预览没有真实插件设置 schema。",
      }));
      const toolsPages: PluginUIPage[] = plugin.toolsTabs.map((title, index) => ({
        id: `tools-${index}`,
        kind: "tools",
        order: index + settingsPages.length,
        pluginId: plugin.id,
        pluginVersion: plugin.version,
        title,
        unavailableReason: "浏览器预览没有真实插件工具 schema。",
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
        { message: "正在下载插件清单。", phase: "download", progress: 0.25, status: "running" },
        options,
      );
      await delay(null, 180);
      previewTask(taskId, { message: "正在安装依赖。", phase: "pip", progress: 0.72, status: "running" }, options);
      await delay(null, 220);
      const plugin: PluginManifest = {
        author: catalog?.author || "Preview",
        description: "浏览器预览安装的插件。",
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
        settingsPages: ["预览设置"],
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
          message: "插件已安装。",
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
    listSlotContributions: () =>
      delay(
        plugins.some((plugin) => plugin.id === "core-tools" && plugin.enabled)
          ? [
              {
                actionLabel: "生成场景提示",
                actionType: "callback" as const,
                actionable: true,
                description: "由宿主安全渲染的浏览器预览贡献。",
                icon: "sparkles" as const,
                id: "scene-prompt",
                order: 100,
                pageId: "",
                pluginId: "core-tools",
                pluginVersion: "built-in",
                presentation: "button" as const,
                slot: "chat-output" as const,
                title: "场景灵感",
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
        message: "浏览器预览动作已执行。",
        pluginId,
      }),
    scanLocal(input) {
      const baseName = input.path.split(/[\\/]/).filter(Boolean).pop() || "preview-plugin";
      return delay({
        author: "Shinsekai Contributors",
        desc: "从本地插件目录生成的示例提交信息。",
        display_name: baseName.replace(/[-_]+/g, " "),
        entry: `plugins.${baseName.replace(/[^A-Za-z0-9_]/g, "_")}.plugin:PreviewPlugin`,
        logo: "logo.png",
        path: input.path,
        repo: `https://github.com/shinsekai/${baseName}`,
        requirements: "",
        social_link: "https://github.com/shinsekai",
        tags: ["preview"],
        warnings: ["浏览器预览使用示例元数据，不会读取真实本地文件。"],
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
        return Promise.reject(new Error(`插件不存在：${id}`));
      }
      return delay({
        message: `操作 ${actionId} 已完成。`,
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
        return Promise.reject(new Error(`插件不存在：${id}`));
      }
      return delay({
        message: "插件设置已保存。",
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
        throw new Error(`插件不存在：${id}`);
      }
      return delay(plugin);
    },
    async uninstall(id) {
      const plugin = plugins.find((item) => item.id === id || item.entry === id);
      if (!plugin) {
        throw new Error(`插件不存在：${id}`);
      }
      plugins = plugins.filter((item) => item.id !== id && item.entry !== id);
      pluginCatalog = pluginCatalog.map((item) =>
        item.entry === id || item.entry === plugin.entry ? { ...item, downloaded: false, installed: false } : item,
      );
      return delay({ message: `${plugin.title} 已卸载。` });
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
        { kind: "mcp-preview", message: "正在连接 MCP 服务。", phase: "probe", progress: 0.4, status: "running" },
        options,
      );
      await delay(null, 220);
      previewTask(
        taskId,
        {
          kind: "mcp-preview",
          message: "工具列表已刷新。",
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
        { kind: "mcp-apply", message: "正在写入 MCP 配置。", phase: "write", progress: 0.45, status: "running" },
        options,
      );
      await delay(null, 180);
      mcpConfig = clone({ ...nextConfig, path: nextConfig.path ?? mcpConfig.path });
      previewTask(
        taskId,
        {
          kind: "mcp-apply",
          message: "MCP 配置已应用。",
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
