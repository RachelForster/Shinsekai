import { getPlatform } from "../../shared/platform/platform";
import type { TaskProgressOptions } from "../../shared/platform/types";
import type {
  AppUpdateRefKind,
  AppUpdateResult,
  PluginConfigActionResult,
  PluginConfigSaveResult,
  McpConfig,
  McpToolPreview,
  PluginInstallInput,
  PluginManifest,
  PluginUIDetail,
} from "./types";

export const pluginCatalogQueryKey = ["plugins", "catalog"] as const;
export const pluginsQueryKey = ["plugins"] as const;
export const mcpConfigQueryKey = ["plugins", "mcp", "config"] as const;

export function pluginUiQueryKey(id: string) {
  return ["plugins", "ui", id] as const;
}

export function listPlugins() {
  return getPlatform().plugins.list();
}

export function getPluginUiDetail(id: string): Promise<PluginUIDetail> {
  return getPlatform().plugins.getUi(id);
}

export function savePluginUiConfig(
  id: string,
  pageId: string,
  values: Record<string, unknown>,
): Promise<PluginConfigSaveResult> {
  return getPlatform().plugins.saveUiConfig(id, pageId, values);
}

export function runPluginUiAction(
  id: string,
  pageId: string,
  actionId: string,
  values: Record<string, unknown>,
): Promise<PluginConfigActionResult> {
  return getPlatform().plugins.runUiAction(id, pageId, actionId, values);
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
