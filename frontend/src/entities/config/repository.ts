import { getPlatform } from "../../shared/platform/platform";
import type { TtsBundleKind, TtsBundleDownloadResult, TaskProgressOptions } from "../../shared/platform/types";
import type { ApiConfig, SystemConfig } from "./types";

export const configQueryKey = ["config"] as const;
export const ttsBundleRecommendationQueryKey = ["config", "tts-bundle", "recommendation"] as const;

export function getAppConfig() {
  return getPlatform().config.get();
}

export function getMemoryStatus(options?: { startLoading?: boolean }) {
  return getPlatform().config.getMemoryStatus(options);
}

export function detectNetworkProxy() {
  return getPlatform().config.detectNetworkProxy();
}

export function fetchLlmModels(input: { apiKey: string; baseUrl: string; provider: string }) {
  return getPlatform().config.fetchLlmModels(input);
}

export function testLlmConnection(input: { apiKey: string; baseUrl: string; model: string; provider: string }) {
  return getPlatform().config.testLlmConnection(input);
}

export function downloadTtsBundle(
  input: { kind: TtsBundleKind },
  options?: TaskProgressOptions<TtsBundleDownloadResult>,
) {
  return getPlatform().config.downloadTtsBundle(input, options);
}

export function cancelTtsBundleDownload(taskId: string) {
  return getPlatform().config.cancelTtsBundleDownload(taskId);
}

export function getTtsBundleRecommendation() {
  return getPlatform().config.getTtsBundleRecommendation();
}

export function saveApiConfig(config: ApiConfig) {
  return getPlatform().config.saveApi(config);
}

export function saveSystemConfig(config: SystemConfig) {
  return getPlatform().config.saveSystem(config);
}
