import { getPlatform } from "../../shared/platform/platform";
import type { TaskProgressOptions } from "../../shared/platform/types";
import type { AppUpdateRefKind, AppUpdateResult, McpConfig, McpToolPreview, PluginInstallInput, PluginManifest } from "./types";

export const pluginCatalogQueryKey = ["plugins", "catalog"] as const;
export const pluginsQueryKey = ["plugins"] as const;
export const mcpConfigQueryKey = ["plugins", "mcp", "config"] as const;

export function listPlugins() {
  return getPlatform().plugins.list();
}

export function listPluginCatalog() {
  return getPlatform().plugins.catalog();
}

export function listRepoTags(repo: string) {
  return getPlatform().plugins.repoTags(repo);
}

export function getAppUpdateInfo() {
  return getPlatform().plugins.appUpdateInfo();
}

export function listAppUpdateTags() {
  return getPlatform().plugins.appUpdateTags();
}

export function runAppUpdate(
  input: { refKind: AppUpdateRefKind; tagName?: string },
  options?: TaskProgressOptions<AppUpdateResult>,
) {
  return getPlatform().plugins.appUpdateRun(input, options);
}

export function setPluginEnabled(id: string, enabled: boolean) {
  return getPlatform().plugins.setEnabled(id, enabled);
}

export function uninstallPlugin(id: string) {
  return getPlatform().plugins.uninstall(id);
}

export function installPlugin(input: PluginInstallInput | string, options?: TaskProgressOptions<PluginManifest>) {
  return getPlatform().plugins.install(input, options);
}

export function getMcpConfig() {
  return getPlatform().mcp.getConfig();
}

export function openMcpConfigFile() {
  return getPlatform().mcp.openConfigFile();
}

export function previewMcpTools(config: McpConfig, options?: TaskProgressOptions<McpToolPreview[]>) {
  return getPlatform().mcp.previewTools(config, options);
}

export function saveAndApplyMcpConfig(config: McpConfig, options?: TaskProgressOptions<McpConfig>) {
  return getPlatform().mcp.saveAndApply(config, options);
}
