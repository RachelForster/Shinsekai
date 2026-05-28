import { getPlatform } from "../../shared/platform/platform";
import type { FileBrowserSnapshot } from "../../shared/platform/types";

export function browseFiles(options?: { path?: string; showHidden?: boolean }): Promise<FileBrowserSnapshot> {
  return getPlatform().files.browse(options);
}

export function fileUrl(path: string): string {
  return getPlatform().files.fileUrl(path);
}

export function openExternal(url: string): Promise<void> {
  return getPlatform().files.openExternal(url);
}
