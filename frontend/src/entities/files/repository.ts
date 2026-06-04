import { getPlatform } from "../../shared/platform/platform";
import type { FileBrowserSnapshot } from "../../shared/platform/types";

const THUMBNAIL_BATCH_SIZE = 128;
const DATA_THUMBNAIL_BATCH_SIZE = 24;
const thumbnailSourceCache = new Map<string, string>();

interface ThumbnailBatchOptions {
  batchSize?: number;
  delivery?: "data" | "url";
  onBatch?: (sources: Record<string, string>) => void;
}

function thumbnailCacheKey(path: string, size: number, delivery: "data" | "url") {
  return `${delivery}\0${size}\0${path}`;
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
  const uniquePaths = [...new Set(paths.filter(Boolean))];
  const result: Record<string, string> = {};
  const missingPaths: string[] = [];

  for (const path of uniquePaths) {
    const cached = thumbnailSourceCache.get(thumbnailCacheKey(path, size, delivery));
    if (cached) {
      result[path] = cached;
    } else {
      missingPaths.push(path);
    }
  }

  if (Object.keys(result).length) {
    options.onBatch?.(result);
  }

  if (!missingPaths.length) {
    return result;
  }

  if (!platform.files.thumbnailBatch) {
    for (const path of missingPaths) {
      const source = platform.files.thumbnailUrl(path, { size });
      thumbnailSourceCache.set(thumbnailCacheKey(path, size, delivery), source);
      result[path] = source;
    }
    options.onBatch?.(Object.fromEntries(missingPaths.map((path) => [path, result[path]])));
    return result;
  }

  const batchSize = Math.max(
    1,
    options.batchSize ?? (delivery === "data" ? DATA_THUMBNAIL_BATCH_SIZE : THUMBNAIL_BATCH_SIZE),
  );
  const loadBatch = async (batch: string[]) => {
    const sources = await platform.files.thumbnailBatch!(batch, { delivery, size }).catch(() =>
      Object.fromEntries(batch.map((path) => [path, platform.files.thumbnailUrl(path, { size })])),
    );
    const loadedSources: Record<string, string> = {};
    for (const [path, source] of Object.entries(sources)) {
      thumbnailSourceCache.set(thumbnailCacheKey(path, size, delivery), source);
      result[path] = source;
      loadedSources[path] = source;
    }
    if (Object.keys(loadedSources).length) {
      options.onBatch?.(loadedSources);
    }
    return loadedSources;
  };

  await Promise.all(chunks(missingPaths, batchSize).map(loadBatch));

  const fallbackSources: Record<string, string> = {};
  for (const path of missingPaths) {
    if (!result[path]) {
      const source = platform.files.thumbnailUrl(path, { size });
      thumbnailSourceCache.set(thumbnailCacheKey(path, size, delivery), source);
      result[path] = source;
      fallbackSources[path] = source;
    }
  }
  if (Object.keys(fallbackSources).length) {
    options.onBatch?.(fallbackSources);
  }

  return result;
}

export function openExternal(url: string): Promise<void> {
  return getPlatform().files.openExternal(url);
}
