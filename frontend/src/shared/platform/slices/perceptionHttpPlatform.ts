import type { HttpTransport } from "../httpTransport";
import type {
  PerceptionHealthProbe,
  PerceptionIngestInput,
  PerceptionIngestResult,
  PerceptionLocalServerStatus,
  PerceptionPlatform,
  PerceptionRuntimeState,
  PerceptionStatusResponse,
} from "./perceptionTypes";

export function createPerceptionHttpPlatform(transport: HttpTransport): PerceptionPlatform {
  const { requestJson } = transport;

  return {
    clear: () =>
      requestJson<{ ok: boolean; accepted: boolean; perception?: PerceptionRuntimeState | null }>(
        "/api/perception/clear",
        {
          body: "{}",
          method: "POST",
        },
      ),
    ingest: (input: PerceptionIngestInput) =>
      requestJson<PerceptionIngestResult>("/api/perception/ingest", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    testImage: (options) =>
      requestJson<PerceptionHealthProbe>("/api/perception/probe-image", {
        body: JSON.stringify(options),
        method: "POST",
      }),
    status: (options) => {
      const params = new URLSearchParams();
      if (options?.probe) params.set("probe", "1");
      if (options?.baseUrl?.trim()) params.set("baseUrl", options.baseUrl.trim());
      if (options?.model?.trim()) params.set("model", options.model.trim());
      if (options?.apiKey?.trim()) params.set("apiKey", options.apiKey.trim());
      if (options?.pythonPath?.trim()) params.set("pythonPath", options.pythonPath.trim());
      const query = params.toString();
      return requestJson<PerceptionStatusResponse>(
        query ? `/api/perception/status?${query}` : "/api/perception/status",
      );
    },
    startServer: (input) =>
      requestJson<{ ok: boolean; localServer: PerceptionLocalServerStatus }>("/api/perception/server/start", {
        body: JSON.stringify(input ?? {}),
        method: "POST",
      }),
    stopServer: () =>
      requestJson<{ ok: boolean; localServer: PerceptionLocalServerStatus }>("/api/perception/server/stop", {
        body: JSON.stringify({}),
        method: "POST",
      }),
  };
}
