import type { HttpTransport } from "../httpTransport";
import type {
  AppUpdateInfo,
  AppUpdateResult,
  McpConfig,
  McpPlatform,
  McpToolPreview,
  PluginCatalogItem,
  PluginConfigActionResult,
  PluginConfigSaveResult,
  PluginLoadStatus,
  PluginLocalScanResult,
  PluginManifest,
  PluginSlotActionResult,
  PluginSlotContribution,
  PluginsPlatform,
  PluginSubmissionClipboardResult,
  PluginSubmissionInput,
  PluginSubmissionIssueResult,
  PluginSubmissionValidationResult,
  PluginUIDetail,
  PluginUninstallResult,
} from "./pluginTypes";
import type { TaskSnapshot } from "./taskTypes";

export function createPluginsHttpPlatform(transport: HttpTransport): PluginsPlatform {
  const { encodePath, requestJson, waitForTask } = transport;

  return {
    async appUpdateRun(input, options) {
      const task = await requestJson<TaskSnapshot<AppUpdateResult>>("/api/plugins/app-update/run", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    appUpdateInfo: () => requestJson<AppUpdateInfo>("/api/plugins/app-update/info"),
    async appUpdateTags() {
      const result = await requestJson<{ tags: string[] }>("/api/plugins/app-update/tags", {
        method: "POST",
      });
      return result.tags;
    },
    catalog: () => requestJson<PluginCatalogItem[]>("/api/plugins/registry"),
    async install(input, options) {
      const body = typeof input === "string" ? { id: input } : input;
      const task = await requestJson<TaskSnapshot<PluginManifest>>("/api/plugins/install", {
        body: JSON.stringify(body),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    getUi: (id) => requestJson<PluginUIDetail>(`/api/plugins/${encodePath(id)}/ui`),
    list: () => requestJson<PluginManifest[]>("/api/plugins"),
    listSlotContributions: () => requestJson<PluginSlotContribution[]>("/api/plugins/chat-ui-contributions"),
    status: () => requestJson<PluginLoadStatus>("/api/plugins/status"),
    async repoTags(repo) {
      const result = await requestJson<{ tags: string[] }>("/api/plugins/repo-tags", {
        body: JSON.stringify({ repo }),
        method: "POST",
      });
      return result.tags;
    },
    scanLocal: (input) =>
      requestJson<PluginLocalScanResult>("/api/plugins/publisher/scan", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    validateSubmission: (input: PluginSubmissionInput) =>
      requestJson<PluginSubmissionValidationResult>("/api/plugins/publisher/validate", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    buildSubmissionIssueUrl: (input: PluginSubmissionInput) =>
      requestJson<PluginSubmissionIssueResult>("/api/plugins/publisher/issue-url", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    async copySubmissionJson(input: PluginSubmissionInput) {
      const result = await requestJson<PluginSubmissionClipboardResult>("/api/plugins/publisher/copy-json", {
        body: JSON.stringify(input),
        method: "POST",
      });
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(result.clipboardText);
      }
      return result;
    },
    runUiAction: (id, pageId, actionId, values) =>
      requestJson<PluginConfigActionResult>(
        `/api/plugins/${encodePath(id)}/ui/${encodePath(pageId)}/actions/${encodePath(actionId)}`,
        { body: JSON.stringify({ values }), method: "POST" },
      ),
    runSlotContribution: (pluginId, contributionId) =>
      requestJson<PluginSlotActionResult>(
        `/api/plugins/${encodePath(pluginId)}/chat-ui/${encodePath(contributionId)}/run`,
        { body: JSON.stringify({}), method: "POST" },
      ),
    saveUiConfig: (id, pageId, values) =>
      requestJson<PluginConfigSaveResult>(`/api/plugins/${encodePath(id)}/ui/${encodePath(pageId)}/config`, {
        body: JSON.stringify({ values }),
        method: "POST",
      }),
    setEnabled: (id, enabled) =>
      requestJson<PluginManifest>(`/api/plugins/${encodePath(id)}/enabled`, {
        body: JSON.stringify({ enabled }),
        method: "POST",
      }),
    uninstall: (id) =>
      requestJson<PluginUninstallResult>(`/api/plugins/${encodePath(id)}`, {
        method: "DELETE",
      }),
  };
}

export function createMcpHttpPlatform(transport: HttpTransport): McpPlatform {
  const { requestJson, waitForTask } = transport;

  return {
    getConfig: () => requestJson<McpConfig>("/api/mcp/config"),
    async openConfigFile() {
      const result = await requestJson<{ path: string }>("/api/mcp/config/open", {
        body: JSON.stringify({}),
        method: "POST",
      });
      return result.path;
    },
    async previewTools(config, options) {
      const task = await requestJson<TaskSnapshot<McpToolPreview[]>>("/api/mcp/preview", {
        body: JSON.stringify({ config }),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    async saveAndApply(config, options) {
      const task = await requestJson<TaskSnapshot<McpConfig>>("/api/mcp/config/apply", {
        body: JSON.stringify({ config }),
        method: "POST",
      });
      return waitForTask(task, options);
    },
  };
}
