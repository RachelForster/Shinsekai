import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { McpSettingsPanel } from "../../../features/plugin-manager/McpSettingsPanel";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { sampleMcpConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const mockGetMcpConfig = vi.fn();
const mockOpenMcpConfigFile = vi.fn();
const mockPreviewMcpTools = vi.fn();
const mockSaveAndApplyMcpConfig = vi.fn();

vi.mock("../../../entities/plugin/repository", () => ({
  getMcpConfig: () => mockGetMcpConfig(),
  mcpConfigQueryKey: ["plugins", "mcp", "config"],
  openMcpConfigFile: () => mockOpenMcpConfigFile(),
  previewMcpTools: (input: unknown, options: unknown) => mockPreviewMcpTools(input, options),
  saveAndApplyMcpConfig: (input: unknown, options: unknown) => mockSaveAndApplyMcpConfig(input, options),
}));

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <McpSettingsPanel />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("McpSettingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMcpConfig.mockResolvedValue(structuredClone(sampleMcpConfig));
    mockOpenMcpConfigFile.mockResolvedValue("data/config/mcp.yaml");
    mockPreviewMcpTools.mockResolvedValue([]);
    mockSaveAndApplyMcpConfig.mockImplementation(async (input) => input);
  });

  it("imports MCP JSON servers into the draft and saves them", async () => {
    renderPanel();

    expect(await screen.findByText("demo_")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import JSON" }));

    const dialog = screen.getByRole("dialog", { name: "Import MCP JSON" });
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: {
        value: JSON.stringify({
          mcpServers: {
            alpha: {
              args: ["server.py"],
              command: "python",
              env: { TOKEN: "secret" },
              type: "stdio",
            },
          },
        }),
      },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Import JSON" }));

    expect(await screen.findByText("alpha_")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save and apply" }));

    await waitFor(() =>
      expect(mockSaveAndApplyMcpConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          servers: expect.arrayContaining([
            expect.objectContaining({ name_prefix: "demo_", transport: "sse" }),
            expect.objectContaining({ command: "python", name_prefix: "alpha_", transport: "stdio" }),
          ]),
        }),
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
  });
});
