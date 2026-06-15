import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRuntimeProviders } from "../app/providers/AppProviders";

const mockApplyThemeColor = vi.fn<(color: string | null | undefined) => void>();
const mockGetAppConfig = vi.fn<() => Promise<unknown>>();

vi.mock("../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
}));

vi.mock("../entities/files/repository", () => ({
  browseFiles: vi.fn(),
}));

vi.mock("../shared/theme/appTheme", () => ({
  applyThemeColor: (color: string | null | undefined) => mockApplyThemeColor(color),
}));

function renderRuntimeProviders() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <AppRuntimeProviders>
        <div>Runtime ready</div>
      </AppRuntimeProviders>
    </QueryClientProvider>,
  );
}

describe("AppRuntimeProviders", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not crash when app config omits system_config", async () => {
    mockGetAppConfig.mockResolvedValue({ api_config: {}, background_list: [], characters: [] });

    renderRuntimeProviders();

    expect(screen.getByText("Runtime ready")).toBeInTheDocument();
    await waitFor(() => expect(mockApplyThemeColor).toHaveBeenCalledWith(undefined));
  });
});
