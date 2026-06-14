import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PluginDetailPanel, resolvePluginFrontendFrameSrc } from "../../../features/plugin-manager/PluginDetailPanel";
import type {
  PluginConfigSaveResult,
  PluginManifest,
  PluginUIDetail,
  PluginUIPage,
} from "../../../entities/plugin/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mockGetPluginUiDetail = vi.fn<() => Promise<PluginUIDetail>>();
const mockSavePluginUiConfig =
  vi.fn<(id: string, pageId: string, values: Record<string, unknown>) => Promise<PluginConfigSaveResult>>();
const mockRunPluginUiAction = vi.fn<
  (
    id: string,
    pageId: string,
    actionId: string,
    values: Record<string, unknown>,
  ) => Promise<{
    message: string;
    page: PluginUIPage;
    plugin: PluginManifest;
    result: Record<string, unknown>;
  }>
>();

vi.mock("../../../entities/plugin/repository", () => ({
  getPluginUiDetail: () => mockGetPluginUiDetail(),
  pluginUiQueryKey: (id: string) => ["plugins", "ui", id],
  pluginsQueryKey: ["plugins"],
  runPluginUiAction: (id: string, pageId: string, actionId: string, values: Record<string, unknown>) =>
    mockRunPluginUiAction(id, pageId, actionId, values),
  savePluginUiConfig: (id: string, pageId: string, values: Record<string, unknown>) =>
    mockSavePluginUiConfig(id, pageId, values),
}));

const plugin: PluginManifest = {
  author: "Tester",
  description: "Plugin with frontend configuration",
  directory: "plugins/frontend_config",
  enabled: true,
  entry: "demo.plugin",
  id: "demo.plugin",
  loaded: true,
  permissions: ["settings"],
  settingsPages: ["settings"],
  slots: ["settings-extension"],
  title: "Demo Plugin",
  toolsTabs: [],
  version: "1.0.0",
};

const configPage: PluginUIPage = {
  description: "Default page description",
  i18n: {
    en: {
      description: "Localized page description",
      groups: {
        main: {
          description: "Localized group description",
          fields: {
            enabled: { label: "Enabled toggle" },
            endpoint: {
              description: "Where requests are sent.",
              label: "Endpoint URL",
              placeholder: "https://example.test",
            },
            extra: { label: "Extra JSON" },
            mode: { label: "Mode", options: { auto: "Automatic", manual: "Manual" } },
          },
          title: "Localized Group",
        },
      },
      restartHint: "Restart from i18n",
      title: "Localized Settings",
    },
  },
  id: "settings",
  kind: "settings",
  order: 0,
  pluginId: "demo.plugin",
  pluginVersion: "1.0.0",
  restartHint: "Restart required",
  schema: [
    {
      fields: [
        { defaultValue: true, key: "enabled", label: "Enabled", type: "boolean" },
        {
          defaultValue: "https://default.test",
          key: "endpoint",
          label: "Endpoint",
          placeholder: "https://default.test",
          type: "url",
        },
        {
          defaultValue: "auto",
          key: "mode",
          label: "Mode",
          options: [
            { label: "Auto", value: "auto" },
            { label: "Manual", value: "manual" },
          ],
          type: "select",
        },
        { defaultValue: { retries: 1 }, key: "extra", label: "Extra", span: "full", type: "json" },
      ],
      id: "main",
      title: "Main",
    },
  ],
  title: "Settings",
  values: {
    enabled: true,
    endpoint: "https://saved.test",
    extra: { retries: 1 },
    mode: "auto",
  },
};

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <PluginDetailPanel detailPlugin={plugin} onBack={vi.fn()} />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("PluginDetailPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, "", "/");
    mockGetPluginUiDetail.mockResolvedValue({ pages: [configPage], plugin });
    mockSavePluginUiConfig.mockImplementation(async (_id, _pageId, values) => ({
      message: "Saved fallback",
      page: { ...configPage, values },
      plugin,
    }));
    mockRunPluginUiAction.mockImplementation(async (_id, _pageId, _actionId, values) => ({
      message: "操作 Reload 已完成。",
      page: { ...configPage, values },
      plugin,
      result: { reloaded: true },
    }));
  });

  it("renders localized frontend configuration schema from plugin UI metadata", async () => {
    renderPanel();

    expect(await screen.findByText("Localized page description")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Localized Group" })).toBeInTheDocument();
    await screen.findByDisplayValue("https://saved.test");
    expect(screen.getByRole("combobox")).toHaveTextContent("Automatic");
    expect(screen.getByLabelText("Extra JSON")).toHaveValue(JSON.stringify({ retries: 1 }, null, 2));
  });

  it("saves the edited draft and shows the localized restart hint", async () => {
    renderPanel();

    const endpointInput = (await screen.findByDisplayValue("https://saved.test")) as HTMLInputElement;
    fireEvent.change(endpointInput, {
      target: { value: "https://edited.test" },
    });
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "Manual" }));
    fireEvent.change(screen.getByLabelText("Extra JSON"), { target: { value: '{"retries":2}' } });
    fireEvent.blur(screen.getByLabelText("Extra JSON"));
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() =>
      expect(mockSavePluginUiConfig).toHaveBeenCalledWith(
        "demo.plugin",
        "settings",
        expect.objectContaining({
          endpoint: "https://edited.test",
          extra: { retries: 2 },
          mode: "manual",
        }),
      ),
    );
    expect(await screen.findByText("Plugin settings saved")).toBeInTheDocument();
    expect(screen.getAllByText("Restart from i18n").length).toBeGreaterThan(1);
  });

  it("renders action buttons and invokes runPluginUiAction on click", async () => {
    const pageWithActions: PluginUIPage = {
      ...configPage,
      actions: [
        { id: "reload", label: "Reload", variant: "primary", order: 50 },
        { id: "reset", label: "Reset", confirm: "Are you sure?", variant: "danger", order: 100 },
      ],
    };
    mockGetPluginUiDetail.mockResolvedValue({ pages: [pageWithActions], plugin });

    renderPanel();

    // Wait for the form to render with saved values
    await screen.findByDisplayValue("https://saved.test");

    const reloadButton = screen.getByRole("button", { name: "Reload" });
    const resetButton = screen.getByRole("button", { name: "Reset" });

    expect(reloadButton).toBeInTheDocument();
    expect(resetButton).toBeInTheDocument();

    // Click action without confirm should call runPluginUiAction immediately
    fireEvent.click(reloadButton);

    await waitFor(() => expect(mockRunPluginUiAction).toHaveBeenCalled());
    expect(mockRunPluginUiAction).toHaveBeenCalledWith(
      "demo.plugin",
      "settings",
      "reload",
      expect.objectContaining({ enabled: true }),
    );
  });

  it("rewrites plugin frontend iframe API URLs through the desktop bridge", async () => {
    window.history.pushState({}, "", "/?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A57891");
    const frontendPage: PluginUIPage = {
      description: "Browser page",
      frontendUrl:
        "/api/plugins/demo%2Fplugin/frontend/browser%20page/?pluginId=demo%2Fplugin&pageId=browser%20page",
      id: "browser page",
      kind: "settings",
      order: 0,
      pluginId: "demo/plugin",
      pluginVersion: "1.0.0",
      title: "Browser Page",
    };
    mockGetPluginUiDetail.mockResolvedValue({ pages: [frontendPage], plugin });

    renderPanel();

    const iframe = (await screen.findByTitle("Browser Page")) as HTMLIFrameElement;
    const frameUrl = new URL(iframe.getAttribute("src") ?? "");
    expect(frameUrl.origin).toBe("http://127.0.0.1:57891");
    expect(frameUrl.pathname).toBe("/api/plugins/demo%2Fplugin/frontend/browser%20page/");
    expect(frameUrl.searchParams.get("pluginId")).toBe("demo/plugin");
    expect(frameUrl.searchParams.get("pageId")).toBe("browser page");
  });

  it("leaves plugin frontend iframe URLs unchanged without a bridge", () => {
    expect(resolvePluginFrontendFrameSrc("/api/plugins/demo/frontend/settings/")).toBe(
      "/api/plugins/demo/frontend/settings/",
    );
    expect(resolvePluginFrontendFrameSrc("https://plugins.example.test/settings/")).toBe(
      "https://plugins.example.test/settings/",
    );
  });
});
