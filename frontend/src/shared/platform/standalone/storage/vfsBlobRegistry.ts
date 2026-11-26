import { translateRuntimeMessage } from "../../../i18n/runtimeLanguage";
import { idbDeleteMany, idbGet, idbGetAll, idbPut, type VfsBlobRecord } from "./indexedDbStore";

export const VFS_SCHEME = "vfs://";

interface HydratedVfsEntry {
  path: string;
  blob: Blob;
  objectUrl: string;
  mimeType: string;
  size: number;
  updatedAtMs: number;
}

const vfsCache = new Map<string, HydratedVfsEntry>();
const objectUrlToVfsPath = new Map<string, string>();
let hydratePromise: Promise<void> | null = null;
let syntheticUrlCounter = 0;

export function isVfsPath(pathOrUrl: string): boolean {
  return typeof pathOrUrl === "string" && pathOrUrl.trim().toLowerCase().startsWith(VFS_SCHEME);
}

export function normalizeVfsPath(rawPath: string): string {
  const trimmed = rawPath.trim().replace(/\\/g, "/");
  const withoutScheme = isVfsPath(trimmed) ? trimmed.slice(VFS_SCHEME.length) : trimmed.replace(/^\.?\/+/, "");
  const segments = withoutScheme
    .split("/")
    .map((seg) => seg.trim())
    .filter((seg) => seg.length > 0 && seg !== ".");

  for (const seg of segments) {
    if (seg === "..") {
      throw new Error(`Unsafe VFS path traversal rejected: ${rawPath}`);
    }
  }
  if (!segments.length) {
    throw new Error(`Empty VFS path: ${rawPath}`);
  }
  return `${VFS_SCHEME}${segments.join("/")}`;
}

export function guessMimeTypeFromPath(path: string, fallback = "application/octet-stream"): string {
  const lower = path.toLowerCase();
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".webp")) return "image/webp";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".gif")) return "image/gif";
  if (lower.endsWith(".svg")) return "image/svg+xml";
  if (lower.endsWith(".mp4")) return "video/mp4";
  if (lower.endsWith(".webm")) return "video/webm";
  if (lower.endsWith(".wav")) return "audio/wav";
  if (lower.endsWith(".mp3")) return "audio/mpeg";
  if (lower.endsWith(".ogg")) return "audio/ogg";
  if (lower.endsWith(".m4a")) return "audio/mp4";
  if (lower.endsWith(".json")) return "application/json";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "text/yaml";
  if (lower.endsWith(".char") || lower.endsWith(".zip")) return "application/zip";
  return fallback;
}

function toSafeBlob(input: Blob | Uint8Array | ArrayBuffer, mimeType: string): Blob {
  if (input instanceof Blob) {
    return input.type === mimeType ? input : new Blob([input], { type: mimeType });
  }
  if (input instanceof ArrayBuffer) {
    return new Blob([input], { type: mimeType });
  }
  const copy = new Uint8Array(input.byteLength);
  copy.set(input);
  return new Blob([copy], { type: mimeType });
}

function createObjectUrlSafe(blob: Blob): string {
  if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
    try {
      return URL.createObjectURL(blob);
    } catch {
      // Fallback for non-browser test environments
    }
  }
  syntheticUrlCounter += 1;
  return `blob:shinsekai-standalone/${syntheticUrlCounter}`;
}

function revokeObjectUrlSafe(url: string): void {
  if (
    url.startsWith("blob:") &&
    !url.startsWith("blob:shinsekai-standalone/") &&
    typeof URL !== "undefined" &&
    typeof URL.revokeObjectURL === "function"
  ) {
    try {
      URL.revokeObjectURL(url);
    } catch {
      // Ignore revoke errors
    }
  }
}

export async function hydrateVfsBlobs(): Promise<void> {
  if (hydratePromise) {
    return hydratePromise;
  }
  hydratePromise = (async () => {
    const records = await idbGetAll<VfsBlobRecord>("vfs_blobs");
    for (const record of records) {
      if (!record?.path || !record.blob) continue;
      if (vfsCache.has(record.path)) continue;
      const mimeType = record.mimeType || record.blob.type || guessMimeTypeFromPath(record.path);
      const typedBlob = toSafeBlob(record.blob, mimeType);
      const objectUrl = createObjectUrlSafe(typedBlob);
      vfsCache.set(record.path, {
        path: record.path,
        blob: typedBlob,
        objectUrl,
        mimeType,
        size: record.size ?? typedBlob.size,
        updatedAtMs: record.updatedAtMs ?? Date.now(),
      });
      objectUrlToVfsPath.set(objectUrl, record.path);
    }
  })();
  return hydratePromise;
}

export async function putVfsBlob(
  rawPath: string,
  blobOrBytes: Blob | Uint8Array | ArrayBuffer,
  options?: { mimeType?: string; persist?: boolean },
): Promise<string> {
  const path = normalizeVfsPath(rawPath);
  const mimeType =
    options?.mimeType ||
    (blobOrBytes instanceof Blob && blobOrBytes.type ? blobOrBytes.type : guessMimeTypeFromPath(path));
  const blob = toSafeBlob(blobOrBytes, mimeType);

  const previous = vfsCache.get(path);
  if (previous) {
    revokeObjectUrlSafe(previous.objectUrl);
  }

  const objectUrl = createObjectUrlSafe(blob);
  const updatedAtMs = Date.now();
  vfsCache.set(path, {
    path,
    blob,
    objectUrl,
    mimeType,
    size: blob.size,
    updatedAtMs,
  });
  objectUrlToVfsPath.set(objectUrl, path);

  if (options?.persist !== false) {
    await idbPut<VfsBlobRecord>("vfs_blobs", {
      path,
      blob,
      mimeType,
      size: blob.size,
      updatedAtMs,
    });
  }
  return objectUrl;
}

export function getVfsBlob(rawPath: string): Blob | undefined {
  if (!rawPath) return undefined;
  try {
    const path = normalizeVfsPath(rawPath);
    return vfsCache.get(path)?.blob;
  } catch {
    return undefined;
  }
}

export async function getVfsBlobAsync(rawPath: string): Promise<Blob | undefined> {
  const cached = getVfsBlob(rawPath);
  if (cached) return cached;
  try {
    const path = normalizeVfsPath(rawPath);
    const record = await idbGet<VfsBlobRecord>("vfs_blobs", path);
    if (!record?.blob) return undefined;
    await putVfsBlob(path, record.blob, { mimeType: record.mimeType, persist: false });
    return vfsCache.get(path)?.blob;
  } catch {
    return undefined;
  }
}

export function resolveVfsUrl(pathOrUrl: string): string {
  if (!pathOrUrl) return "";
  if (!isVfsPath(pathOrUrl)) {
    return pathOrUrl;
  }
  try {
    const normalized = normalizeVfsPath(pathOrUrl);
    return vfsCache.get(normalized)?.objectUrl ?? normalized;
  } catch {
    return pathOrUrl;
  }
}

export function unresolveVfsUrl(urlOrPath: string): string {
  if (!urlOrPath) return "";
  const mapped = objectUrlToVfsPath.get(urlOrPath);
  if (mapped) {
    return mapped;
  }
  for (const [path, entry] of vfsCache.entries()) {
    if (entry.objectUrl === urlOrPath) {
      return path;
    }
  }
  return urlOrPath;
}

export function listVfsEntries(prefix?: string): Array<{
  path: string;
  size: number;
  mimeType: string;
  updatedAtMs: number;
}> {
  const normalizedPrefix = prefix ? normalizeVfsPath(prefix) : VFS_SCHEME;
  const results: Array<{ path: string; size: number; mimeType: string; updatedAtMs: number }> = [];
  for (const entry of vfsCache.values()) {
    if (
      normalizedPrefix === VFS_SCHEME ||
      entry.path === normalizedPrefix ||
      entry.path.startsWith(`${normalizedPrefix}/`)
    ) {
      results.push({
        path: entry.path,
        size: entry.size,
        mimeType: entry.mimeType,
        updatedAtMs: entry.updatedAtMs,
      });
    }
  }
  return results.sort((a, b) => a.path.localeCompare(b.path));
}

export function listVfsPaths(prefix?: string): string[] {
  return listVfsEntries(prefix).map((item) => item.path);
}

export async function deleteVfsPath(rawPath: string): Promise<void> {
  if (!rawPath) return;
  let path: string;
  try {
    path = normalizeVfsPath(rawPath);
  } catch {
    return;
  }
  const existing = vfsCache.get(path);
  if (existing) {
    revokeObjectUrlSafe(existing.objectUrl);
    vfsCache.delete(path);
  }
  for (const [url, mappedPath] of objectUrlToVfsPath.entries()) {
    if (mappedPath === path) {
      objectUrlToVfsPath.delete(url);
    }
  }
  await idbDeleteMany("vfs_blobs", [path]);
}

export async function relocateVfsBlob(sourcePath: string, targetPath: string): Promise<string> {
  if (!sourcePath || !isVfsPath(sourcePath)) {
    return sourcePath;
  }
  const normalizedSource = normalizeVfsPath(sourcePath);
  const normalizedTarget = normalizeVfsPath(targetPath);
  if (normalizedSource === normalizedTarget) {
    return normalizedSource;
  }
  const blob = await getVfsBlobAsync(normalizedSource);
  if (!blob) {
    throw new Error(translateRuntimeMessage("plat.standalone.vfsMissingUpload", { path: sourcePath }));
  }
  await putVfsBlob(normalizedTarget, blob, {
    mimeType: blob.type || guessMimeTypeFromPath(normalizedTarget),
    persist: true,
  });
  if (normalizedSource.startsWith(`${VFS_SCHEME}uploads/`)) {
    await deleteVfsPath(normalizedSource);
  }
  return normalizedTarget;
}

export async function deleteVfsPrefix(prefix: string): Promise<number> {
  const normalizedPrefix = normalizeVfsPath(prefix);
  const keysToDelete: string[] = [];
  for (const [key, entry] of vfsCache.entries()) {
    if (key === normalizedPrefix || key.startsWith(`${normalizedPrefix}/`)) {
      revokeObjectUrlSafe(entry.objectUrl);
      vfsCache.delete(key);
      keysToDelete.push(key);
    }
  }
  for (const [url, mappedPath] of objectUrlToVfsPath.entries()) {
    if (mappedPath === normalizedPrefix || mappedPath.startsWith(`${normalizedPrefix}/`)) {
      objectUrlToVfsPath.delete(url);
    }
  }
  await idbDeleteMany("vfs_blobs", keysToDelete);
  return keysToDelete.length;
}

function sanitizeFileName(name: string): string {
  const cleaned = name.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_").trim();
  return cleaned || "file.bin";
}

export async function stageUploadedFiles(files: File[], subdir = "uploads"): Promise<string[]> {
  const paths: string[] = [];
  const batchTs = Date.now();
  for (let i = 0; i < files.length; i += 1) {
    const file = files[i];
    const safeName = sanitizeFileName(file.name);
    const vfsPath = normalizeVfsPath(`${subdir}/${batchTs}-${i}-${safeName}`);
    await putVfsBlob(vfsPath, file, {
      mimeType: file.type || guessMimeTypeFromPath(safeName),
      persist: true,
    });
    paths.push(vfsPath);
  }
  return paths;
}

export function resetVfsRegistryForTests(): void {
  for (const entry of vfsCache.values()) {
    revokeObjectUrlSafe(entry.objectUrl);
  }
  vfsCache.clear();
  objectUrlToVfsPath.clear();
  hydratePromise = null;
}
