import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PluginDetailPanel } from "../../../features/plugin-manager/PluginDetailPanel";
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

vi.mock("../../../entities/plugin/repository", () => ({
  getPluginUiDetail: () => mockGetPluginUiDetail(),
  pluginUiQueryKey: (id: string) => ["plugins", "ui", id],
  pluginsQueryKey: ["plugins"],
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
    mockGetPluginUiDetail.mockResolvedValue({ pages: [configPage], plugin });
    mockSavePluginUiConfig.mockImplementation(async (_id, _pageId, values) => ({
      message: "Saved fallback",
      page: { ...configPage, values },
      plugin,
    }));
  });

  it("renders localized frontend configuration schema from plugin UI metadata", async () => {
    renderPanel();

    expect(await screen.findByText("Localized page description")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Localized Group" })).toBeInTheDocument();
    expect((screen.getByLabelText(/Endpoint URL/) as HTMLInputElement).value).toMatch(/^https:\/\/saved\.test\/?$/);
    expect(screen.getByRole("combobox")).toHaveTextContent("Automatic");
    expect(screen.getByLabelText("Extra JSON")).toHaveValue(JSON.stringify({ retries: 1 }, null, 2));
  });

  it("saves the edited draft and shows the localized restart hint", async () => {
    renderPanel();

    const endpointInput = (await screen.findByLabelText(/Endpoint URL/)) as HTMLInputElement;
    expect(endpointInput.value).toMatch(/^https:\/\/saved\.test\/?$/);
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
});
