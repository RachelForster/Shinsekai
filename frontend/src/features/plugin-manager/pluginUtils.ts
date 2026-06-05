import type {
  PluginConfigFieldType,
  PluginConfigI18nMap,
  PluginConfigGroupSchema,
  PluginCatalogItem,
  PluginInstallInput,
  PluginManifest,
  PluginUIPage,
} from "../../entities/plugin/types";
import type { FieldKind, FormGroupSchema } from "../../shared/form-schema";
import type { FrontendLanguage } from "../../shared/i18n/messages";

export type PluginView = "installed" | "discover" | "mcp";
export type PluginConfigDraft = Record<string, unknown>;

export function catalogInstallSource(item: PluginCatalogItem) {
  return githubRepoSlug(item.repo) || item.repo.trim();
}

export function githubUrl(repo: string) {
  const pageUrl = githubPageUrl(repo);
  if (pageUrl) {
    return pageUrl;
  }
  const slug = githubRepoSlug(repo);
  return slug ? `https://github.com/${slug}` : "";
}

function githubPageUrl(repo: string) {
  const raw = repo.trim();
  if (!raw) {
    return "";
  }
  if (/^git@github\.com:/i.test(raw)) {
    return "";
  }
  const withProtocol = /^github\.com\//i.test(raw) ? `https://${raw}` : raw;
  if (!/^https?:\/\/github\.com\//i.test(withProtocol)) {
    return "";
  }
  try {
    const parsed = new URL(withProtocol);
    const parts = parsed.pathname
      .split("/")
      .map((part) => part.trim())
      .filter(Boolean);
    if (parts.length < 2) {
      return "";
    }
    parts[1] = parts[1].replace(/\.git$/i, "");
    return `https://github.com/${parts.join("/")}${parsed.search}${parsed.hash}`;
  } catch {
    return "";
  }
}

export function githubRepoSlug(repo: string) {
  let raw = repo.trim();
  if (!raw) {
    return "";
  }
  raw = raw
    .replace(/^git@github\.com:/i, "")
    .replace(/^https?:\/\/github\.com\//i, "")
    .replace(/^github\.com\//i, "")
    .split("#", 1)[0]
    .split("?", 1)[0]
    .replace(/^\/+|\/+$/g, "");
  if (raw.endsWith(".git")) {
    raw = raw.slice(0, -4);
  }
  const parts = raw.split("/").filter(Boolean);
  return parts.length >= 2 ? `${parts[0]}/${parts[1]}` : "";
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

function localizedPageI18n(i18n: PluginConfigI18nMap | undefined, language: FrontendLanguage) {
  if (!i18n) {
    return undefined;
  }
  return i18n[language] ?? i18n.en ?? i18n.zh_CN ?? Object.values(i18n)[0];
}

export function localizePluginUiPage(page: PluginUIPage, language: FrontendLanguage): PluginUIPage {
  const pageI18n = localizedPageI18n(page.i18n, language);
  if (!pageI18n) {
    return page;
  }
  const groups = pageI18n.groups ?? {};
  return {
    ...page,
    description: pageI18n.description ?? page.description,
    restartHint: pageI18n.restartHint ?? page.restartHint,
    schema: page.schema?.map((group) => {
      const groupI18n = groups[group.id] ?? {};
      const fields = groupI18n.fields ?? {};
      return {
        ...group,
        description: groupI18n.description ?? group.description,
        fields: group.fields.map((field) => {
          const fieldI18n = fields[field.key] ?? {};
          const optionLabels = fieldI18n.options ?? {};
          return {
            ...field,
            description: fieldI18n.description ?? field.description,
            label: fieldI18n.label ?? field.label,
            options: field.options?.map((option) => ({
              ...option,
              label: optionLabels[option.value] ?? option.label,
            })),
            placeholder: fieldI18n.placeholder ?? field.placeholder,
          };
        }),
        title: groupI18n.title ?? group.title,
      };
    }),
    title: pageI18n.title ?? page.title,
  };
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

export function pluginConfigGroupsToFormGroups(
  groups: PluginConfigGroupSchema[],
): Array<FormGroupSchema<PluginConfigDraft>> {
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
      pathKind: field.pathKind,
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
