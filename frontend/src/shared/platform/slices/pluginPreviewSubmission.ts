import type { PluginCatalogItem, PluginManifest, PluginSubmissionInput } from "./pluginTypes";

export const PREVIEW_PLUGIN_SUBMIT_URL =
  "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new?template=PLUGIN_PUBLISH.yml";

export function previewNormalizePluginKey(value: string | null | undefined) {
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

export function previewModuleToken(value: string | null | undefined) {
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

export function previewPluginDirectory(entry: string, fallback: string) {
  const token = previewModuleToken(entry) || previewNormalizePluginKey(fallback) || "preview";
  return `plugins/${token.replace(/[^A-Za-z0-9_\u3040-\u30ff\u3400-\u9fff]+/g, "_")}`;
}

export function previewCatalogKeys(plugin: PluginCatalogItem) {
  return new Set(
    [plugin.id, plugin.name, plugin.repo, plugin.entry, previewModuleToken(plugin.entry)]
      .map(previewNormalizePluginKey)
      .filter((key) => key.length >= 2),
  );
}

export function previewManifestKeys(plugin: PluginManifest) {
  return new Set(
    [
      plugin.id,
      plugin.entry,
      plugin.directory?.split(/[\\/]/).filter(Boolean).at(-1),
      plugin.install?.repo,
      plugin.install?.entry,
      previewModuleToken(plugin.entry),
    ]
      .map(previewNormalizePluginKey)
      .filter((key) => key.length >= 2),
  );
}

export function previewCatalogForSource(source: string, catalogItems: PluginCatalogItem[]) {
  const sourceKey = previewNormalizePluginKey(source);
  const rawLower = source.trim().toLowerCase();
  return catalogItems.find(
    (item) =>
      previewCatalogKeys(item).has(sourceKey) ||
      Boolean(rawLower && (item.displayName ?? "").trim().toLowerCase() === rawLower),
  );
}

export function previewUpsertPlugin(
  currentPlugins: PluginManifest[],
  plugin: PluginManifest,
  catalog?: PluginCatalogItem,
) {
  const keys = new Set([...previewManifestKeys(plugin), ...(catalog ? previewCatalogKeys(catalog) : [])]);
  let replaced = false;
  const nextPlugins = currentPlugins.map((item) => {
    for (const key of previewManifestKeys(item)) {
      if (keys.has(key)) {
        replaced = true;
        return plugin;
      }
    }
    return item;
  });
  if (!replaced) {
    return [...nextPlugins, plugin];
  }
  return nextPlugins;
}

export function normalizePreviewPluginSubmission(input: PluginSubmissionInput): PluginSubmissionInput {
  const submission: PluginSubmissionInput = {
    author: input.author.trim(),
    desc: input.desc.trim(),
    display_name: input.display_name.trim(),
    repo: input.repo.trim().replace(/\.git$/i, ""),
    social_link: (input.social_link ?? "").trim(),
    tags: (input.tags ?? [])
      .map((tag) => tag.trim())
      .filter(Boolean)
      .slice(0, 5),
  };
  const lowestShinsekaiVersion = (input.lowest_shinsekai_version ?? "").trim();
  if (lowestShinsekaiVersion) {
    submission.lowest_shinsekai_version = lowestShinsekaiVersion;
  }
  return submission;
}

export function previewPluginSubmissionErrors(input: PluginSubmissionInput) {
  const submission = normalizePreviewPluginSubmission(input);
  const errors: string[] = [];
  for (const field of ["display_name", "desc", "author", "repo"] as const) {
    if (!submission[field]) {
      errors.push(`${field} is required`);
    }
  }
  if (submission.desc.length > 200) {
    errors.push("desc must be 200 characters or less");
  }
  if (!/^https:\/\/github\.com\/[^/\s]+\/[^/\s]+$/i.test(submission.repo)) {
    errors.push("repo must be a GitHub repository URL");
  }
  if ((input.tags ?? []).filter((tag) => tag.trim()).length > 5) {
    errors.push("tags must contain 5 items or fewer");
  }
  return errors;
}

export function previewPluginSubmissionJson(input: PluginSubmissionInput) {
  return JSON.stringify(normalizePreviewPluginSubmission(input), null, 2);
}

export function previewPluginIssueUrl(input: PluginSubmissionInput) {
  const submission = normalizePreviewPluginSubmission(input);
  const params = new URLSearchParams({
    "plugin-info": ["```json", previewPluginSubmissionJson(submission), "```", ""].join("\n"),
    template: "PLUGIN_PUBLISH.yml",
    title: `[Plugin] ${submission.display_name}`,
  });
  return `${PREVIEW_PLUGIN_SUBMIT_URL.split("?")[0]}?${params.toString()}`;
}
