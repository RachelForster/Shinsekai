import type { PluginSlotId } from "../../shared/platform/types";

export type {
  AppUpdateInfo,
  AppUpdateRefKind,
  AppUpdateResult,
  McpConfig,
  McpServerEntry,
  McpToolPreview,
  McpTransport,
  PluginCatalogItem,
  PluginConfigFieldSchema,
  PluginConfigFieldType,
  PluginConfigGroupSchema,
  PluginConfigOption,
  PluginConfigSaveResult,
  PluginInstallInput,
  PluginManifest,
  PluginSlotId,
  PluginUIDetail,
  PluginUIPage,
  PluginUIPageKind,
} from "../../shared/platform/types";

export const pluginSlotIds: PluginSlotId[] = ["chat-output", "chat-toolbar", "settings-extension", "settings-tools"];

export function isPluginSlotId(value: string): value is PluginSlotId {
  return pluginSlotIds.includes(value as PluginSlotId);
}
