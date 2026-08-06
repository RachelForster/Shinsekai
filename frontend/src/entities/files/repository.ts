import { getPlatform } from "../../shared/platform/platform";
import type { FileBrowserSnapshot } from "../../shared/platform/types";
import { normalizePathSeparatorsForIdentity } from "../../shared/paths/pathContract";

const THUMBNAIL_BATCH_SIZE = 128;
const DATA_THUMBNAIL_BATCH_SIZE = 24;
const thumbnailSourceCache = new Map<string, string>();

interface ThumbnailBatchOptions {
  batchSize?: number;
  delivery?: "data" | "url";
  onBatch?: (sources: Record<string, string>) => void;
}

function thumbnailCacheKey(path: string, size: number, delivery: "data" | "url") {
  return `${delivery}\0${size}\0${normalizePathSeparatorsForIdentity(path)}`;
}

function chunks<T>(items: T[], size: number): T[][] {
  const result: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    result.push(items.slice(index, index + size));
  }
  return result;
}

export function browseFiles(options?: { path?: string; showHidden?: boolean }): Promise<FileBrowserSnapshot> {
  return getPlatform().files.browse(options);
}

export function fileUrl(path: string): string {
  return getPlatform().files.fileUrl(path);
}

export function fileThumbnailUrl(path: string, size = 160): string {
  return getPlatform().files.thumbnailUrl(path, { size });
}

export async function fileThumbnailBatch(
  paths: string[],
  size = 160,
  options: ThumbnailBatchOptions = {},
): Promise<Record<string, string>> {
  const platform = getPlatform();
  const delivery = options.delivery ?? "url";
  const aliasesByIdentity = new Map<string, string[]>();
  const representativeByIdentity = new Map<string, string>();
  for (const path of new Set(paths.filter(Boolean))) {
    const identity = normalizePathSeparatorsForIdentity(path);
    const aliases = aliasesByIdentity.get(identity);
    if (aliases) {
      aliases.push(path);
    } else {
      aliasesByIdentity.set(identity, [path]);
      representativeByIdentity.set(identity, path);
    }
  }
  const uniquePaths = [...representativeByIdentity.values()];
  const resultByIdentity = new Map<string, string>();
  const missingPaths: string[] = [];

  const resultForIdentities = (identities: Iterable<string>): Record<string, string> =>
    Object.fromEntries(
      [...identities].flatMap((identity) => {
        const source = resultByIdentity.get(identity);
        if (source === undefined) {
          return [];
        }
        return (aliasesByIdentity.get(identity) ?? []).map((path) => [path, source]);
      }),
    );
  const publishIdentities = (identities: Iterable<string>) => {
    const sources = resultForIdentities(identities);
    if (Object.keys(sources).length) {
      options.onBatch?.(sources);
    }
  };
  const completeResult = () => resultForIdentities(representativeByIdentity.keys());

  const cachedIdentities: string[] = [];
  for (const path of uniquePaths) {
    const identity = normalizePathSeparatorsForIdentity(path);
    const cached = thumbnailSourceCache.get(thumbnailCacheKey(path, size, delivery));
    if (cached) {
      resultByIdentity.set(identity, cached);
      cachedIdentities.push(identity);
    } else {
      missingPaths.push(path);
    }
  }

  publishIdentities(cachedIdentities);

  if (!missingPaths.length) {
    return completeResult();
  }

  if (!platform.files.thumbnailBatch) {
    const loadedIdentities: string[] = [];
    for (const path of missingPaths) {
      const identity = normalizePathSeparatorsForIdentity(path);
      const source = platform.files.thumbnailUrl(path, { size });
      thumbnailSourceCache.set(thumbnailCacheKey(path, size, delivery), source);
      resultByIdentity.set(identity, source);
      loadedIdentities.push(identity);
    }
    publishIdentities(loadedIdentities);
    return completeResult();
  }

  const batchSize = Math.max(
    1,
    options.batchSize ?? (delivery === "data" ? DATA_THUMBNAIL_BATCH_SIZE : THUMBNAIL_BATCH_SIZE),
  );
  const loadBatch = async (batch: string[]) => {
    const batchPathsByIdentity = new Map(
      batch.map((path) => [normalizePathSeparatorsForIdentity(path), path] as const),
    );
    const sources = await platform.files.thumbnailBatch!(batch, { delivery, size }).catch(() =>
      Object.fromEntries(batch.map((path) => [path, platform.files.thumbnailUrl(path, { size })])),
    );
    const loadedIdentities = new Set<string>();
    for (const [path, source] of Object.entries(sources)) {
      const identity = normalizePathSeparatorsForIdentity(path);
      const requestedPath = batchPathsByIdentity.get(identity);
      if (!requestedPath || loadedIdentities.has(identity)) {
        continue;
      }
      thumbnailSourceCache.set(thumbnailCacheKey(requestedPath, size, delivery), source);
      resultByIdentity.set(identity, source);
      loadedIdentities.add(identity);
    }
    publishIdentities(loadedIdentities);
  };

  await Promise.all(chunks(missingPaths, batchSize).map(loadBatch));

  const fallbackIdentities: string[] = [];
  for (const path of missingPaths) {
    const identity = normalizePathSeparatorsForIdentity(path);
    if (!resultByIdentity.has(identity)) {
      const source = platform.files.thumbnailUrl(path, { size });
      thumbnailSourceCache.set(thumbnailCacheKey(path, size, delivery), source);
      resultByIdentity.set(identity, source);
      fallbackIdentities.push(identity);
    }
  }
  publishIdentities(fallbackIdentities);

  return completeResult();
}

export function openExternal(url: string): Promise<void> {
  return getPlatform().files.openExternal(url);
}
