import { getPlatform } from "../../shared/platform/platform";
import type {
  PerceptionEndpointOptions,
  PerceptionIngestInput,
  PerceptionLocalServerStartInput,
} from "../../shared/platform/types";

export function getPerceptionStatus(options?: PerceptionEndpointOptions & { probe?: boolean }) {
  return getPlatform().perception.status(options);
}

export function testPerceptionImage(options: PerceptionEndpointOptions) {
  return getPlatform().perception.testImage(options);
}

export function ingestPerception(input: PerceptionIngestInput) {
  return getPlatform().perception.ingest(input);
}

export function clearPerception() {
  return getPlatform().perception.clear();
}

export function startPerceptionLocalServer(input?: PerceptionLocalServerStartInput) {
  return getPlatform().perception.startServer(input);
}

export function stopPerceptionLocalServer() {
  return getPlatform().perception.stopServer();
}
