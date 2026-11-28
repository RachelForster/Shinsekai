import type { FrontendLanguage } from "../i18n";
import type {
  PluginConfigFieldI18n,
  PluginConfigGroupI18n,
  PluginConfigGroupSchema,
  PluginSectionContribution,
  PluginSidebarPageContribution,
  PluginSlotContribution,
  PluginUIPage,
} from "../platform/types";

function languageLookupCandidates(language: FrontendLanguage): string[] {
  if (language === "zh_CN") {
    return ["zh_CN", "zh-CN", "zh_cn", "zh"];
  }
  if (language === "ja") {
    return ["ja", "ja_JP", "ja-JP", "jp"];
  }
  return ["en", "en_US", "en-US"];
}

export function resolveLocalizedEntry<T>(
  i18n: Record<string, T> | undefined,
  language: FrontendLanguage,
): T | undefined {
  if (!i18n || typeof i18n !== "object") {
    return undefined;
  }
  for (const key of languageLookupCandidates(language)) {
    if (key in i18n && i18n[key] !== undefined) {
      return i18n[key];
    }
  }
  if ("en" in i18n && i18n.en !== undefined) {
    return i18n.en;
  }
  if ("zh_CN" in i18n && i18n.zh_CN !== undefined) {
    return i18n.zh_CN;
  }
  if ("zh" in i18n && i18n.zh !== undefined) {
    return i18n.zh;
  }
  const values = Object.values(i18n);
  return values[0];
}

export function resolveLocalizedText(
  i18n: Record<string, string> | undefined,
  language: FrontendLanguage,
  fallback = "",
): string {
  const matched = resolveLocalizedEntry(i18n, language);
  if (typeof matched === "string" && matched.trim()) {
    return matched;
  }
  return fallback;
}

export function localizePluginSchemaGroups(
  schema: PluginConfigGroupSchema[] | undefined,
  groupsI18n?: Record<string, PluginConfigGroupI18n>,
  fieldsI18n?: Record<string, PluginConfigFieldI18n>,
): PluginConfigGroupSchema[] | undefined {
  if (!schema) {
    return undefined;
  }
  const groups = groupsI18n ?? {};
  const topFields = fieldsI18n ?? {};
  return schema.map((group) => {
    const groupI18n = groups[group.id] ?? {};
    const groupFields = groupI18n.fields ?? {};
    return {
      ...group,
      description: groupI18n.description ?? group.description,
      fields: group.fields.map((field) => {
        const fieldI18n = groupFields[field.key] ?? topFields[field.key] ?? {};
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
  });
}

export function localizePluginUiPage(page: PluginUIPage, language: FrontendLanguage): PluginUIPage {
  const pageI18n = resolveLocalizedEntry(page.i18n, language);
  if (!pageI18n) {
    return page;
  }
  return {
    ...page,
    description: pageI18n.description ?? page.description,
    navLabel: pageI18n.navLabel ?? page.navLabel,
    restartHint: pageI18n.restartHint ?? page.restartHint,
    schema: localizePluginSchemaGroups(page.schema, pageI18n.groups),
    title: pageI18n.title ?? page.title,
  };
}

export function localizePluginSlotContribution(
  item: PluginSlotContribution,
  language: FrontendLanguage,
): PluginSlotContribution {
  const entry = resolveLocalizedEntry(item.i18n, language);
  if (!entry) {
    return item;
  }
  return {
    ...item,
    actionLabel: entry.label ?? item.actionLabel,
    description: entry.description ?? entry.tooltip ?? item.description,
    title: entry.title ?? entry.label ?? item.title,
  };
}

export function localizePluginSidebarPage(
  item: PluginSidebarPageContribution,
  language: FrontendLanguage,
): PluginSidebarPageContribution {
  const entry = resolveLocalizedEntry(item.i18n, language);
  if (!entry) {
    return item;
  }
  return {
    ...item,
    description: entry.description ?? item.description,
    navLabel: entry.navLabel ?? entry.title ?? item.navLabel,
    title: entry.title ?? entry.navLabel ?? item.title,
  };
}

export function localizePluginSection(
  item: PluginSectionContribution,
  language: FrontendLanguage,
): PluginSectionContribution {
  const entry = resolveLocalizedEntry(item.i18n, language);
  if (!entry) {
    return item;
  }
  const actionsI18n = entry.actions ?? {};
  return {
    ...item,
    actions: item.actions?.map((action) => {
      const actionEntry = actionsI18n[action.id];
      if (!actionEntry) {
        return action;
      }
      return {
        ...action,
        confirm: actionEntry.confirm ?? action.confirm,
        description: actionEntry.description ?? action.description,
        label: actionEntry.label ?? action.label,
      };
    }),
    description: entry.description ?? item.description,
    navLabel: entry.navLabel ?? entry.title ?? item.navLabel,
    schema: localizePluginSchemaGroups(item.schema, entry.groups, entry.fields),
    title: entry.title ?? entry.navLabel ?? item.title,
  };
}
