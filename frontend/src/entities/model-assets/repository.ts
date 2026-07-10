import { getPlatform } from "../../shared/platform/platform";
import type { ModelAssetDownloadResult, ModelAssetRef, TaskProgressOptions } from "../../shared/platform/types";

export function getModelAssetStatus(input: ModelAssetRef) {
  return getPlatform().modelAssets.status(input);
}

export function downloadModelAsset(input: ModelAssetRef, options?: TaskProgressOptions<ModelAssetDownloadResult>) {
  return getPlatform().modelAssets.download(input, options);
}
