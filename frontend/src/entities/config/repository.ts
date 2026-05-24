import { getPlatform } from "../../shared/platform/platform";
import type { TtsBundleKind, TtsBundleDownloadResult, TaskProgressOptions } from "../../shared/platform/types";
import type { ApiConfig, SystemConfig } from "./types";

export const configQueryKey = ["config"] as const;

export function getAppConfig() {
  return getPlatform().config.get();
}

export function fetchLlmModels(input: { apiKey: string; baseUrl: string; provider: string }) {
  return getPlatform().config.fetchLlmModels(input);
}

export function downloadTtsBundle(input: { kind: TtsBundleKind }, options?: TaskProgressOptions<TtsBundleDownloadResult>) {
  return getPlatform().config.downloadTtsBundle(input, options);
}

export function saveApiConfig(config: ApiConfig) {
  return getPlatform().config.saveApi(config);
}

export function saveSystemConfig(config: SystemConfig) {
  return getPlatform().config.saveSystem(config);
}
