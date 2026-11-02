import type { PropsWithChildren } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useVisionAvailability } from "../../../features/media-auto-label/useVisionAvailability";

const mocks = vi.hoisted(() => ({
  getAppConfig: vi.fn(),
  getPluginLoadStatus: vi.fn(),
}));

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mocks.getAppConfig(),
}));

vi.mock("../../../entities/plugin/repository", () => ({
  getPluginLoadStatus: () => mocks.getPluginLoadStatus(),
  pluginLoadStatusQueryKey: ["plugins", "status"],
}));

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }

  return { client, Wrapper };
}

describe("useVisionAvailability", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("refreshes unavailable config after asynchronous plugins become ready", async () => {
    mocks.getPluginLoadStatus.mockResolvedValueOnce({ status: "loading" }).mockResolvedValue({ status: "ready" });
    mocks.getAppConfig.mockResolvedValueOnce({ vision_available: false }).mockResolvedValue({ vision_available: true });
    const { client, Wrapper } = createWrapper();

    const { result, unmount } = renderHook(() => useVisionAvailability(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current).toBe(true), { timeout: 2_000 });
    expect(mocks.getPluginLoadStatus).toHaveBeenCalledTimes(2);
    expect(mocks.getAppConfig).toHaveBeenCalledTimes(2);

    unmount();
    client.clear();
  });
});
