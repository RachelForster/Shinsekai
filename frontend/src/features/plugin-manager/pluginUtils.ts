import type { PluginCatalogItem, PluginInstallInput, PluginManifest, PluginUIPage } from "../../entities/plugin/types";

export type { PluginConfigDraft } from "../../shared/plugin/pluginConfigSchema";
export {
  pluginConfigGroupsToFormGroups,
  pluginConfigInitialValues,
  pluginFieldTypeToFormType,
} from "../../shared/plugin/pluginConfigSchema";
export { localizePluginUiPage } from "../../shared/plugin/pluginI18n";

export type PluginView = "installed" | "discover" | "mcp";

export function catalogInstallSource(item: PluginCatalogItem) {
  if (item.packageUrl || item.downloadUrl) {
    return (item.id || item.name).trim();
  }
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

export function normalizePluginKey(value: string | null | undefined) {
  return (value ?? "")
    .trim()
    .toLowerCase()
    .replace(/^git@github\.com:/i, "")
    .replace(/^https?:\/\/github\.com\//i, "")
    .replace(/^github\.com\//i, "")
    .replace(/\.git$/i, "")
    .replace(/[^\p{L}\p{N}]+/gu, "_")
    .replace(/^_+|_+$/g, "");
}

export function normalizeManifestEntryKey(value: string | null | undefined) {
  const raw = (value ?? "").trim().toLowerCase();
  if (!raw) {
    return "";
  }
  return raw.startsWith("plugins.") ? raw.slice("plugins.".length) : raw;
}

export function pluginModuleToken(value: string | null | undefined) {
  const moduleName = (value ?? "").split(":", 1)[0] ?? "";
  const parts = moduleName.split(".").filter(Boolean);
  if (!parts.length) {
    return "";
  }
  if (parts.at(-1) === "plugin" && parts.length > 1) {
    return parts.at(-2) ?? "";
  }
  return parts.at(-1) ?? "";
}

export function installedPluginTechnicalKeys(plugin: PluginManifest) {
  return new Set(
    [
      plugin.id,
      plugin.directory?.split(/[\\/]/).filter(Boolean).at(-1),
      pluginModuleToken(plugin.entry),
      pluginModuleToken(plugin.install?.entry),
    ]
      .map(normalizePluginKey)
      .filter((key) => key.length >= 2),
  );
}

export function catalogPluginTechnicalKeys(plugin: PluginCatalogItem) {
  return new Set(
    [plugin.id, plugin.name, githubRepoSlug(plugin.repo ?? ""), pluginModuleToken(plugin.entry)]
      .map(normalizePluginKey)
      .filter((key) => key.length >= 2),
  );
}

function scorePluginCatalogMatch(plugin: PluginManifest, catalog: PluginCatalogItem) {
  const catalogEntry = normalizeManifestEntryKey(catalog.entry);
  if (catalogEntry) {
    const installedEntries = new Set(
      [plugin.entry, plugin.install?.entry].map(normalizeManifestEntryKey).filter(Boolean),
    );
    if (installedEntries.has(catalogEntry)) {
      return 1_000_000 + catalogEntry.length;
    }
  }

  const catalogRepo = githubRepoSlug(catalog.repo ?? "").toLowerCase();
  const installedRepo = githubRepoSlug(plugin.install?.repo ?? "").toLowerCase();
  if (catalogRepo && installedRepo && catalogRepo === installedRepo) {
    return 500_000 + catalogRepo.length;
  }

  const installedKeys = installedPluginTechnicalKeys(plugin);
  let longestKeyLength = 0;
  for (const key of catalogPluginTechnicalKeys(catalog)) {
    if (installedKeys.has(key) && key.length > longestKeyLength) {
      longestKeyLength = key.length;
    }
  }
  return longestKeyLength;
}

export function findInstalledCatalogMatch(plugin: PluginManifest, catalogItems: PluginCatalogItem[]) {
  let bestMatch: PluginCatalogItem | undefined;
  let bestScore = 0;
  for (const item of catalogItems) {
    const score = scorePluginCatalogMatch(plugin, item);
    if (score > bestScore) {
      bestScore = score;
      bestMatch = item;
    }
  }
  return bestMatch;
}

export function findCatalogInstalledMatch(catalog: PluginCatalogItem, plugins: PluginManifest[]) {
  let bestMatch: PluginManifest | undefined;
  let bestScore = 0;
  for (const plugin of plugins) {
    const score = scorePluginCatalogMatch(plugin, catalog);
    if (score > bestScore) {
      bestScore = score;
      bestMatch = plugin;
    }
  }
  return bestMatch;
}

export function catalogDisplayName(plugin: PluginCatalogItem | null | undefined) {
  const raw = plugin as (PluginCatalogItem & { display_name?: string; title?: string }) | null | undefined;
  return plugin?.displayName || raw?.display_name || raw?.title || plugin?.name || "";
}

export function catalogDescription(plugin: PluginCatalogItem | null | undefined) {
  return (plugin?.shortDescription || plugin?.description || "").trim();
}

function defaultDerivedPluginTitle(pluginId: string) {
  const trimmed = pluginId.trim();
  if (!trimmed) {
    return "";
  }
  const tail = trimmed.split(".").at(-1) ?? trimmed;
  return tail.replace(/_/g, " ").trim() || trimmed;
}

function offlineEntryFallbackTitle(entry: string | null | undefined) {
  const value = (entry ?? "").trim();
  if (!value) {
    return "";
  }
  if (value.includes(":")) {
    return value.slice(value.lastIndexOf(":") + 1);
  }
  return value.includes(".") ? value.slice(value.lastIndexOf(".") + 1) : value;
}

export function installedPluginDisplayName(plugin: PluginManifest, catalog?: PluginCatalogItem) {
  const loaded = plugin.loaded !== false;
  const localTitle = (plugin.title ?? "").trim();
  const catalogName = catalogDisplayName(catalog).trim();
  const hasCuratedCatalogName = Boolean(catalogName && catalogName !== catalog?.name);

  if (loaded && localTitle) {
    const isRawTechnicalFallback =
      localTitle === plugin.id ||
      localTitle === catalog?.name ||
      localTitle === offlineEntryFallbackTitle(plugin.entry) ||
      (hasCuratedCatalogName && localTitle.toLowerCase() === defaultDerivedPluginTitle(plugin.id).toLowerCase());
    if (!isRawTechnicalFallback) {
      return localTitle;
    }
  }

  if (hasCuratedCatalogName) {
    return catalogName;
  }
  if (localTitle && localTitle !== plugin.id) {
    return localTitle;
  }
  return catalogName || localTitle || plugin.id;
}

export function installedPluginTechnicalName(
  plugin: PluginManifest,
  catalog: PluginCatalogItem | undefined,
  displayName: string,
) {
  if (catalog?.name && catalog.name !== displayName) {
    return catalog.name;
  }
  if (plugin.id && plugin.id !== displayName) {
    return plugin.id;
  }
  if (plugin.title && plugin.title !== displayName) {
    return plugin.title;
  }
  return "";
}

export function installedPluginDescription(
  plugin: PluginManifest,
  catalog: PluginCatalogItem | undefined,
  unavailableFallback: string,
) {
  const loaded = plugin.loaded !== false;
  if (!loaded && plugin.enabled) {
    return plugin.loadError || unavailableFallback;
  }
  const localDescription = (plugin.description ?? "").trim();
  if (localDescription) {
    return localDescription;
  }
  return catalogDescription(catalog);
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
