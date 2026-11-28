import type {
  PluginConfigAction,
  PluginConfigFieldI18n,
  PluginConfigGroupI18n,
  PluginConfigGroupSchema,
  PluginSlotContributionIcon,
} from "./pluginTypes";

export interface PluginActionRunContext {
  entityId?: string | null;
  entityType?: string | null;
  extra?: Record<string, unknown>;
  locale?: string;
  page?: string;
}

export interface PluginSidebarPageI18n {
  description?: string;
  navLabel?: string;
  title?: string;
}

export interface PluginSidebarPageContribution {
  description: string;
  frontendUrl: string;
  i18n?: Record<string, PluginSidebarPageI18n>;
  navIcon: PluginSlotContributionIcon;
  navLabel: string;
  order: number;
  pageId: string;
  pluginId: string;
  pluginVersion: string;
  title: string;
}

export type PluginSectionPageId = "api" | "background" | "character" | "effect" | "system" | "template";
export type PluginSectionSlotId = "main" | "sidebar";

export interface PluginSectionQuery {
  entityId?: string;
  entityType?: string;
  extra?: Record<string, unknown>;
  locale?: string;
  page: PluginSectionPageId | string;
}

export interface PluginSectionActionI18n {
  confirm?: string;
  description?: string;
  label?: string;
}

export interface PluginSectionI18n {
  actions?: Record<string, PluginSectionActionI18n>;
  description?: string;
  fields?: Record<string, PluginConfigFieldI18n>;
  groups?: Record<string, PluginConfigGroupI18n>;
  navLabel?: string;
  title?: string;
}

export interface PluginSectionContribution {
  actions?: PluginConfigAction[];
  canSave?: boolean;
  description: string;
  frontendUrl?: string;
  i18n?: Record<string, PluginSectionI18n>;
  id: string;
  maxHeight?: number;
  minHeight?: number;
  navLabel: string;
  order: number;
  page: string;
  pageId?: string;
  pluginId: string;
  pluginVersion: string;
  renderer: "iframe" | "schema";
  schema?: PluginConfigGroupSchema[];
  slot: PluginSectionSlotId;
  title: string;
  values?: Record<string, unknown>;
}

export interface PluginSectionSaveResult {
  i18nMessage?: Record<string, string>;
  kind: "error" | "info" | "success" | "warning";
  message: string;
  refresh?: string[];
  section: PluginSectionContribution;
}

export interface PluginSectionActionResult extends PluginSectionSaveResult {
  result?: unknown;
}
