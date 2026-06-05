import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PluginManagerPage } from "../../../features/plugin-manager/PluginManagerPage";
import type { PluginManifest, PluginUIDetail, PluginUIPage } from "../../../entities/plugin/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mockGetPluginUiDetail = vi.fn<() => Promise<PluginUIDetail>>();
const mockListPlugins = vi.fn<() => Promise<PluginManifest[]>>();

vi.mock("../../../entities/plugin/repository", () => ({
  getAppUpdateInfo: vi.fn(),
  getPluginUiDetail: () => mockGetPluginUiDetail(),
  installPlugin: vi.fn(),
  listAppUpdateTags: vi.fn(),
  listPluginCatalog: vi.fn(),
  listPlugins: () => mockListPlugins(),
  pluginCatalogQueryKey: ["plugins", "catalog"],
  pluginsQueryKey: ["plugins"],
  pluginUiQueryKey: (id: string) => ["plugins", "ui", id],
  runAppUpdate: vi.fn(),
  savePluginUiConfig: vi.fn(),
  setPluginEnabled: vi.fn(),
  uninstallPlugin: vi.fn(),
}));

const configurablePlugin: PluginManifest = {
  author: "Tester",
  description: "Has a frontend configuration page.",
  directory: "plugins/configurable",
  enabled: true,
  entry: "plugins.configurable:Plugin",
  id: "configurable",
  loaded: true,
  permissions: ["settings"],
  settingsPages: ["Settings"],
  slots: ["settings-extension"],
  title: "Configurable Plugin",
  toolsTabs: [],
  version: "1.0.0",
};

const plainPlugin: PluginManifest = {
  author: "Tester",
  description: "No frontend configuration.",
  directory: "plugins/plain",
  enabled: true,
  entry: "plugins.plain:Plugin",
  id: "plain",
  loaded: true,
  permissions: [],
  settingsPages: [],
  slots: [],
  title: "Plain Plugin",
  toolsTabs: [],
  version: "1.0.0",
};

const unloadedPlugin: PluginManifest = {
  ...configurablePlugin,
  description: "Configured but not loaded.",
  entry: "plugins.unloaded:Plugin",
  id: "unloaded",
  loaded: false,
  title: "Unloaded Plugin",
};

const detailPage: PluginUIPage = {
  description: "Dynamic detail description",
  id: "settings",
  kind: "settings",
  order: 0,
  pluginId: "configurable",
  pluginVersion: "1.0.0",
  schema: [
    {
      fields: [{ defaultValue: "ready", key: "status", label: "Status", type: "text" }],
      id: "main",
      title: "Dynamic Group",
    },
  ],
  title: "Dynamic Settings",
  values: { status: "ready" },
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <PluginManagerPage />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function pluginCard(title: string) {
  return screen.getByText(title).closest(".plugin-card") as HTMLElement;
}

async function findPluginCard(title: string) {
  return (await screen.findByText(title)).closest(".plugin-card") as HTMLElement;
}

describe("PluginManagerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetPluginUiDetail.mockResolvedValue({ pages: [detailPage], plugin: configurablePlugin });
    mockListPlugins.mockResolvedValue([configurablePlugin, plainPlugin, unloadedPlugin]);
  });

  it("shows configuration actions only for plugins that expose frontend pages", async () => {
    renderPage();

    const configurable = await screen.findByText("Configurable Plugin");
    const configurableCard = configurable.closest(".plugin-card") as HTMLElement;
    expect(within(configurableCard).getByRole("button", { name: "Plugin settings" })).toBeEnabled();

    expect(within(pluginCard("Plain Plugin")).queryByRole("button", { name: "Plugin settings" })).toBeNull();
    expect(within(pluginCard("Unloaded Plugin")).getByRole("button", { name: "Plugin settings" })).toBeDisabled();
  });

  it("opens the dynamic frontend configuration detail from the plugin card", async () => {
    renderPage();

    fireEvent.click(
      await within(await findPluginCard("Configurable Plugin")).findByRole("button", { name: "Plugin settings" }),
    );

    expect(await screen.findByText("Dynamic detail description")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dynamic Group" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("ready")).toBeInTheDocument();
    expect(mockGetPluginUiDetail).toHaveBeenCalledTimes(1);
  });
});
