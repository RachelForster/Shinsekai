import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { McpSettingsPanel } from "../../../features/plugin-manager/McpSettingsPanel";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { sampleMcpConfig, sampleMcpTools } from "../../../shared/platform/sampleData";
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

  it("opens the config file, previews tools, and filters server/tool rows", async () => {
    const tools = [
      ...sampleMcpTools,
      ...Array.from({ length: 11 }, (_, index) => ({
        description: `Tool ${index + 1}`,
        name: `tool-${index + 1}`,
        prefix: "demo_",
        registered_name: `demo_tool_${index + 1}`,
      })),
    ];
    mockPreviewMcpTools.mockImplementation(async (_input, options) => {
      options?.onTaskUpdate?.({
        createdAt: 1,
        id: "preview-task",
        kind: "mcp-preview",
        logs: ["ready"],
        message: "done",
        phase: "completed",
        progress: 1,
        result: tools,
        status: "succeeded",
        title: "preview",
        updatedAt: 2,
      });
      return tools;
    });
    renderPanel();

    expect(await screen.findByText("demo_")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open YAML" }));
    await waitFor(() => expect(mockOpenMcpConfigFile).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByPlaceholderText("Search MCP servers"), { target: { value: "missing" } });
    expect(await screen.findByText("No matching items")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Search MCP servers"), { target: { value: "demo" } });
    expect(await screen.findByText("demo_")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Preview tools" }));
    await waitFor(() => expect(mockPreviewMcpTools).toHaveBeenCalledWith(sampleMcpConfig, expect.any(Object)));
    expect(await screen.findByText("demo_search")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Next page" }).some((button) => !button.hasAttribute("disabled")),
    ).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("Search MCP tools"), { target: { value: "demo_tool_11" } });
    expect(await screen.findByText("demo_tool_11")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Search MCP tools"), { target: { value: "does-not-exist" } });
    expect(await screen.findByText("No matching items")).toBeInTheDocument();
  });

  it("adds and edits MCP servers with validation for HTTP and stdio transports", async () => {
    renderPanel();

    await screen.findByText("demo_");
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    let dialog = screen.getByRole("dialog", { name: "Add MCP server" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save server" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("URL is required for HTTP MCP servers.");

    fireEvent.change(within(dialog).getByLabelText("Name prefix"), { target: { value: "http_" } });
    fireEvent.change(within(dialog).getByLabelText("URL"), { target: { value: "https://mcp.example/sse" } });
    fireEvent.change(within(dialog).getByLabelText("Headers JSON"), {
      target: { value: JSON.stringify({ Authorization: "Bearer token" }) },
    });
    fireEvent.change(within(dialog).getByLabelText("Call timeout"), { target: { value: "60" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save server" }));

    expect(await screen.findByText("http_")).toBeInTheDocument();
    expect(screen.getByText("https://mcp.example/sse")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" }).at(-1)!);
    dialog = screen.getByRole("dialog", { name: "Edit MCP server" });
    fireEvent.click(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "stdio" }));
    fireEvent.change(within(dialog).getByLabelText("Name prefix"), { target: { value: "node_" } });
    fireEvent.change(within(dialog).getByLabelText("Command"), { target: { value: "node" } });
    fireEvent.change(within(dialog).getByLabelText("Args JSON"), { target: { value: JSON.stringify(["server.js"]) } });
    fireEvent.change(within(dialog).getByLabelText("Env JSON"), {
      target: { value: JSON.stringify({ TOKEN: "secret" }) },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save server" }));

    expect(await screen.findByText("node_")).toBeInTheDocument();
    expect(screen.getByText("node server.js")).toBeInTheDocument();
  });

  it("removes a server from the draft before saving", async () => {
    renderPanel();

    expect(await screen.findByText("demo_")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete MCP server" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("No MCP servers")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save and apply" }));

    await waitFor(() =>
      expect(mockSaveAndApplyMcpConfig).toHaveBeenCalledWith(
        expect.objectContaining({ servers: [] }),
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
  });
});
