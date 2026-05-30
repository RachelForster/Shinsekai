import type { PluginConfigFieldType, PluginConfigGroupSchema, PluginCatalogItem, PluginInstallInput, PluginManifest, PluginUIPage } from "../../entities/plugin/types";
import type { FieldKind, FormGroupSchema } from "../../shared/form-schema";

export type PluginView = "installed" | "discover" | "mcp";
export type PluginConfigDraft = Record<string, unknown>;

export function catalogInstallSource(item: PluginCatalogItem) {
  return item.repo;
}

export function githubUrl(repo: string) {
  return repo ? `https://github.com/${repo}` : "";
}

export function pluginSettingsPages(plugin: PluginManifest | null) {
  return plugin?.settingsPages ?? [];
}

export function pluginToolsTabs(plugin: PluginManifest | null) {
  return plugin?.toolsTabs ?? [];
}

export function pluginActionId(plugin: PluginManifest) {
  return plugin.entry || plugin.id;
}

export function pluginHasManifestEntry(plugin: PluginManifest) {
  return Boolean(plugin.entry?.trim());
}

export function pluginInstallSource(input: PluginInstallInput | string) {
  return typeof input === "string" ? input : input.source;
}

export function pluginUiPageKey(page: PluginUIPage) {
  return `${page.kind}:${page.id}`;
}

export function fallbackPluginUiPages(plugin: PluginManifest | null): PluginUIPage[] {
  if (!plugin) {
    return [];
  }
  const settingsPages = plugin.settingsPages.map((title, index) => ({
    id: `settings-${index}`,
    kind: "settings" as const,
    order: index,
    pluginId: plugin.id,
    pluginVersion: plugin.version,
    title,
    unavailableReason: "",
  }));
  const toolsPages = plugin.toolsTabs.map((title, index) => ({
    id: `tools-${index}`,
    kind: "tools" as const,
    order: settingsPages.length + index,
    pluginId: plugin.id,
    pluginVersion: plugin.version,
    title,
    unavailableReason: "",
  }));
  return [...settingsPages, ...toolsPages];
}

export function pluginFieldTypeToFormType(type: PluginConfigFieldType): FieldKind {
  if (type === "boolean") {
    return "checkbox";
  }
  return type;
}

export function pluginConfigGroupsToFormGroups(groups: PluginConfigGroupSchema[]): Array<FormGroupSchema<PluginConfigDraft>> {
  return groups.map((group) => ({
    columns: 1,
    description: group.description,
    fields: group.fields.map((field) => ({
      defaultValue: field.defaultValue,
      description: field.description,
      label: field.label,
      max: field.max,
      min: field.min,
      name: field.key,
      options: field.options,
      placeholder: field.placeholder,
      required: field.required,
      span: field.span,
      step: field.step,
      type: pluginFieldTypeToFormType(field.type),
    })),
    id: group.id,
    title: group.title,
  }));
}

export function pluginConfigInitialValues(page: PluginUIPage): PluginConfigDraft {
  const values = page.values ?? {};
  const draft: PluginConfigDraft = {};
  for (const group of page.schema ?? []) {
    for (const field of group.fields) {
      draft[field.key] = Object.prototype.hasOwnProperty.call(values, field.key)
        ? values[field.key]
        : field.defaultValue;
    }
  }
  return draft;
}
