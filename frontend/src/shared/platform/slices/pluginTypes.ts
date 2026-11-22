import type { TaskProgressOptions } from "./taskTypes";

export type PluginSlotId =
  | "chat-dialog-actions"
  | "chat-output"
  | "chat-toolbar"
  | "chat-top-toolbar"
  | "chat-workspace-actions"
  | "settings-extension"
  | "settings-tools";

export type PluginSlotContributionActionType = "callback" | "none" | "open-plugin-page";
export type PluginSlotContributionPageMode = "navigate" | "overlay";
export type PluginSlotContributionIcon = "info" | "play" | "puzzle" | "settings" | "smartphone" | "sparkles";
export type PluginSlotContributionPresentation = "button" | "icon-only";
export type PluginSlotContributionVariant = "danger" | "ghost" | "primary";

export interface PluginSlotContribution {
  externalLaunch?: boolean;
  actionLabel: string;
  actionType: PluginSlotContributionActionType;
  actionable: boolean;
  description: string;
  icon: PluginSlotContributionIcon;
  id: string;
  order: number;
  pageId: string;
  pageMode?: PluginSlotContributionPageMode;
  pluginId: string;
  pluginVersion: string;
  presentation: PluginSlotContributionPresentation;
  slot: PluginSlotId;
  title: string;
  variant: PluginSlotContributionVariant;
}

export interface PluginSlotActionResult {
  conversationId?: string;
  id: string;
  kind: "error" | "info" | "success";
  message: string;
  pluginId: string;
}

export type AppUpdateRefKind = "latest" | "head" | "tag";

export interface AppUpdateInfo {
  repo: string;
  version: string;
}

export interface AppUpdateResult {
  detail?: string;
  frontendDistUpdated?: boolean;
  message: string;
  pipCode?: string;
  version: string;
}

export interface PluginInstallMetadata {
  dependencyDetail?: string;
  dependencyStatus?: string;
  entry?: string;
  packageSha256?: string;
  packageSize?: number | null;
  packageSource?: string;
  packageStatus?: string;
  packageUrl?: string;
  refKind?: AppUpdateRefKind;
  repo?: string;
  sourceLabel?: string;
  sourceType?: string;
  tagName?: string;
}

export interface PluginManifest {
  author: string;
  description: string;
  directory?: string;
  enabled: boolean;
  entry: string;
  id: string;
  install?: PluginInstallMetadata;
  loadError?: string;
  loaded: boolean;
  permissions: string[];
  settingsPages: string[];
  slots: PluginSlotId[];
  title: string;
  toolsTabs: string[];
  version: string;
}

export interface PluginLoadStatus {
  error?: string;
  status: "error" | "idle" | "loading" | "ready";
}

export interface PluginCatalogItem {
  author: string;
  commitSha?: string;
  description: string;
  downloadCount?: number;
  displayName?: string;
  downloadUrl?: string;
  downloaded: boolean;
  entry: string;
  forks?: number;
  id?: string;
  installed: boolean;
  logo?: string;
  name: string;
  packageR2Key?: string;
  packageSha256?: string;
  packageSize?: number | null;
  packageSource?: string;
  packageUrl?: string;
  readmeUrl?: string;
  repo: string;
  review?: Record<string, unknown>;
  securityScan?: Record<string, unknown>;
  sha256?: string;
  lowestShinsekaiVersion?: string;
  shortDescription?: string;
  size?: number | null;
  socialLink?: string;
  sourceUrl?: string;
  stars?: number;
  tags?: string[];
  trustLevel?: string;
  updatedAt?: string;
  verified?: boolean;
  version?: string;
}

export type PluginUIPageKind = "settings" | "tools";

export interface PluginInstallInput {
  overwrite?: boolean;
  refKind?: AppUpdateRefKind;
  source: string;
  tagName?: string;
}

export interface PluginSubmissionInput {
  author: string;
  desc: string;
  display_name: string;
  lowest_shinsekai_version?: string;
  repo: string;
  social_link?: string;
  tags: string[];
}

export interface PluginLocalScanResult extends PluginSubmissionInput {
  entry?: string;
  logo?: string;
  path: string;
  requirements?: string;
  shinsekai_version?: string;
  warnings: string[];
}

export interface PluginSubmissionPayload {
  json: string;
  submission: PluginSubmissionInput;
}

export interface PluginSubmissionValidationResult extends Partial<PluginSubmissionPayload> {
  errors: string[];
  ok: boolean;
}

export interface PluginSubmissionIssueResult extends PluginSubmissionPayload {
  issueUrl: string;
  submitUrl: string;
}

export interface PluginSubmissionClipboardResult extends PluginSubmissionPayload {
  clipboardText: string;
  message: string;
}

export interface PluginUninstallResult {
  folderNote?: string;
  message: string;
}

export interface PluginPagePresentation {
  mode: "overlay";
  pageId: string;
  payload: Record<string, unknown>;
  pluginId: string;
  presentationId: string;
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

export type PluginConfigFieldType =
  | "boolean"
  | "file"
  | "integer"
  | "json"
  | "number"
  | "password"
  | "select"
  | "text"
  | "textarea"
  | "url";

export interface PluginConfigOption {
  label: string;
  value: string;
}

export interface PluginConfigFieldSchema {
  defaultValue?: unknown;
  description?: string;
  key: string;
  label: string;
  max?: number;
  min?: number;
  options?: PluginConfigOption[];
  pathKind?: "directory" | "file";
  placeholder?: string;
  required?: boolean;
  span?: "full";
  step?: number;
  type: PluginConfigFieldType;
  visibleWhen?: Record<string, unknown>;
}

export interface PluginConfigGroupSchema {
  description?: string;
  fields: PluginConfigFieldSchema[];
  id: string;
  title: string;
}

export interface PluginConfigFieldI18n {
  description?: string;
  label?: string;
  options?: Record<string, string>;
  placeholder?: string;
}

export interface PluginConfigGroupI18n {
  description?: string;
  fields?: Record<string, PluginConfigFieldI18n>;
  title?: string;
}

export interface PluginConfigPageI18n {
  description?: string;
  groups?: Record<string, PluginConfigGroupI18n>;
  restartHint?: string;
  title?: string;
}

export type PluginConfigI18nMap = Record<string, PluginConfigPageI18n>;

export type PluginConfigActionVariant = "danger" | "ghost" | "primary";

export interface PluginConfigAction {
  confirm?: string;
  description?: string;
  id: string;
  label: string;
  order: number;
  variant: PluginConfigActionVariant;
}

export interface PluginUIPage {
  actions?: PluginConfigAction[];
  description?: string;
  frontendUrl?: string;
  i18n?: PluginConfigI18nMap;
  id: string;
  kind: PluginUIPageKind;
  order: number;
  pluginId: string;
  pluginVersion: string;
  restartHint?: string;
  schema?: PluginConfigGroupSchema[];
  title: string;
  unavailableReason?: string;
  values?: Record<string, unknown>;
}

export interface PluginUIDetail {
  pages: PluginUIPage[];
  plugin: PluginManifest;
}

export interface PluginConfigSaveResult {
  message: string;
  page: PluginUIPage;
  plugin: PluginManifest;
}

export interface PluginConfigActionResult {
  message: string;
  page: PluginUIPage;
  plugin: PluginManifest;
  result: Record<string, unknown>;
}

export interface PluginsPlatform {
  appUpdateInfo: () => Promise<AppUpdateInfo>;
  appUpdateTags: () => Promise<string[]>;
  appUpdateRun: (
    input: { refKind: AppUpdateRefKind; tagName?: string },
    options?: TaskProgressOptions<AppUpdateResult>,
  ) => Promise<AppUpdateResult>;
  catalog: () => Promise<PluginCatalogItem[]>;
  install: (
    input: PluginInstallInput | string,
    options?: TaskProgressOptions<PluginManifest>,
  ) => Promise<PluginManifest>;
  getUi: (id: string) => Promise<PluginUIDetail>;
  list: () => Promise<PluginManifest[]>;
  listSlotContributions: () => Promise<PluginSlotContribution[]>;
  status: () => Promise<PluginLoadStatus>;
  repoTags: (repo: string) => Promise<string[]>;
  scanLocal: (input: { path: string }) => Promise<PluginLocalScanResult>;
  validateSubmission: (input: PluginSubmissionInput) => Promise<PluginSubmissionValidationResult>;
  buildSubmissionIssueUrl: (input: PluginSubmissionInput) => Promise<PluginSubmissionIssueResult>;
  copySubmissionJson: (input: PluginSubmissionInput) => Promise<PluginSubmissionClipboardResult>;
  runUiAction: (
    id: string,
    pageId: string,
    actionId: string,
    values: Record<string, unknown>,
  ) => Promise<PluginConfigActionResult>;
  runSlotContribution: (pluginId: string, contributionId: string) => Promise<PluginSlotActionResult>;
  saveUiConfig: (id: string, pageId: string, values: Record<string, unknown>) => Promise<PluginConfigSaveResult>;
  setEnabled: (id: string, enabled: boolean) => Promise<PluginManifest>;
  uninstall: (id: string) => Promise<PluginUninstallResult>;
}

export interface McpPlatform {
  getConfig: () => Promise<McpConfig>;
  openConfigFile: () => Promise<string>;
  previewTools: (config: McpConfig, options?: TaskProgressOptions<McpToolPreview[]>) => Promise<McpToolPreview[]>;
  saveAndApply: (config: McpConfig, options?: TaskProgressOptions<McpConfig>) => Promise<McpConfig>;
}
