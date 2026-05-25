export type PluginSlotId = "chat-output" | "chat-toolbar" | "settings-extension" | "settings-tools";

export const pluginSlotIds: PluginSlotId[] = ["chat-output", "chat-toolbar", "settings-extension", "settings-tools"];

export function isPluginSlotId(value: string): value is PluginSlotId {
  return pluginSlotIds.includes(value as PluginSlotId);
}

export interface PluginManifest {
  author: string;
  description: string;
  directory?: string;
  enabled: boolean;
  entry: string;
  id: string;
  loadError?: string;
  loaded: boolean;
  permissions: string[];
  settingsPages: string[];
  slots: PluginSlotId[];
  title: string;
  toolsTabs: string[];
  version: string;
}

export interface PluginCatalogItem {
  author: string;
  description: string;
  downloaded: boolean;
  entry: string;
  installed: boolean;
  name: string;
  repo: string;
}

export type AppUpdateRefKind = "latest" | "head" | "tag";

export interface AppUpdateInfo {
  repo: string;
  version: string;
}

export interface AppUpdateResult {
  detail?: string;
  message: string;
  pipCode?: string;
  version: string;
}

export interface PluginInstallInput {
  overwrite?: boolean;
  refKind?: AppUpdateRefKind;
  source: string;
  tagName?: string;
}

export type McpTransport = "sse" | "stdio" | "streamable_http";

export interface McpServerEntry {
  args?: string[];
  call_timeout?: number;
  command?: string;
  enabled: boolean;
  env?: Record<string, string>;
  group?: string;
  headers?: Record<string, string>;
  name_prefix: string;
  transport: McpTransport;
  url?: string;
}

export interface McpConfig {
  default_call_timeout: number;
  enabled: boolean;
  path?: string;
  servers: McpServerEntry[];
}

export interface McpToolPreview {
  description: string;
  name: string;
  prefix: string;
  registered_name: string;
}

export type PluginConfigFieldType = "boolean" | "number" | "password" | "select" | "text" | "textarea" | "url";

export interface PluginConfigOption {
  label: string;
  value: string;
}

export interface PluginConfigFieldSchema {
  defaultValue?: boolean | number | string;
  description?: string;
  key: string;
  label: string;
  options?: PluginConfigOption[];
  required?: boolean;
  type: PluginConfigFieldType;
}

export interface PluginConfigGroupSchema {
  description?: string;
  fields: PluginConfigFieldSchema[];
  id: string;
  title: string;
}
