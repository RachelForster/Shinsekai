import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PluginManagerPage } from "../../../features/plugin-manager/PluginManagerPage";
import type {
  PluginCatalogItem,
  PluginInstallInput,
  PluginManifest,
  PluginUIDetail,
  PluginUIPage,
} from "../../../entities/plugin/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { TaskProgressOptions } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mockGetPluginUiDetail = vi.fn<() => Promise<PluginUIDetail>>();
const mockGetAppUpdateInfo = vi.fn();
const mockInstallPlugin =
  vi.fn<
    (input: PluginInstallInput | string, options?: TaskProgressOptions<PluginManifest>) => Promise<PluginManifest>
  >();
const mockListAppUpdateTags = vi.fn<() => Promise<string[]>>();
const mockListPluginCatalog = vi.fn<() => Promise<PluginCatalogItem[]>>();
const mockListPlugins = vi.fn<() => Promise<PluginManifest[]>>();
const mockListRepoTags = vi.fn<() => Promise<string[]>>();
const mockOpenExternal = vi.fn();
const mockRunAppUpdate = vi.fn();
const mockIsTauriDesktop = vi.fn(() => false);
const mockReloadPluginService = vi.fn<() => Promise<unknown>>();

vi.mock("../../../entities/plugin/repository", () => ({
  getAppUpdateInfo: () => mockGetAppUpdateInfo(),
  getPluginUiDetail: () => mockGetPluginUiDetail(),
  installPlugin: (input: PluginInstallInput | string, options?: TaskProgressOptions<PluginManifest>) =>
    mockInstallPlugin(input, options),
  buildPluginSubmissionIssueUrl: vi.fn(),
  copyPluginSubmissionJson: vi.fn(),
  listAppUpdateTags: () => mockListAppUpdateTags(),
  listPluginCatalog: () => mockListPluginCatalog(),
  listPlugins: () => mockListPlugins(),
  listRepoTags: () => mockListRepoTags(),
  pluginCatalogQueryKey: ["plugins", "catalog"],
  pluginsQueryKey: ["plugins"],
  pluginUiQueryKey: (id: string) => ["plugins", "ui", id],
  runAppUpdate: (...args: unknown[]) => mockRunAppUpdate(...args),
  savePluginUiConfig: vi.fn(),
  scanLocalPlugin: vi.fn(),
  setPluginEnabled: vi.fn(),
  uninstallPlugin: vi.fn(),
  validatePluginSubmission: vi.fn(),
}));

vi.mock("../../../entities/files/repository", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../entities/files/repository")>();
  return {
    ...actual,
    openExternal: (...args: unknown[]) => mockOpenExternal(...args),
  };
});

vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/desktop/desktopApi")>();
  return {
    ...actual,
    isTauriDesktop: () => mockIsTauriDesktop(),
  };
});

vi.mock("../../../features/plugin-manager/pluginReload", () => ({
  reloadPluginService: () => mockReloadPluginService(),
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

const catalogItem: PluginCatalogItem = {
  author: "Registry Author",
  description: "Registry description",
  displayName: "Registry Display",
  downloaded: false,
  entry: "plugins.registry_display.plugin:RegistryDisplayPlugin",
  id: "registry-display",
  installed: false,
  name: "registry_display",
  packageSha256: "abcdef1234567890",
  packageSize: 12345,
  packageSource: "r2",
  packageUrl: "https://example.invalid/registry-display.zip",
  repo: "owner/registry-display",
  securityScan: { static: { pass: true } },
  sha256: "abcdef1234567890",
  lowestShinsekaiVersion: ">=0.2.0",
  shortDescription: "Registry short description",
  size: 12345,
  stars: 1,
  tags: ["demo"],
  trustLevel: "community",
  updatedAt: "2026-06-06T00:00:00Z",
  verified: false,
  version: "0.2.0",
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

const phonePage: PluginUIPage = {
  ...detailPage,
  description: "Phone panel",
  id: "phone",
  schema: [
    {
      fields: [{ defaultValue: true, key: "enabled", label: "Enabled", type: "boolean" }],
      id: "phone-main",
      title: "Phone controls",
    },
  ],
  title: "Phone",
  values: { enabled: true },
};

function LocationProbe() {
  const location = useLocation();
  return (
    <output aria-label="location">
      {location.pathname}
      {JSON.stringify(location.state)}
    </output>
  );
}

function renderPage(
  initialEntries: Parameters<typeof MemoryRouter>[0]["initialEntries"] = ["/settings/plugins"],
  includeLocationProbe = false,
) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <MemoryRouter
            future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
            initialEntries={initialEntries}
          >
            <PluginManagerPage />
            {includeLocationProbe ? <LocationProbe /> : null}
          </MemoryRouter>
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
    mockIsTauriDesktop.mockReturnValue(false);
    mockReloadPluginService.mockResolvedValue(undefined);
    mockGetPluginUiDetail.mockResolvedValue({ pages: [detailPage], plugin: configurablePlugin });
    mockInstallPlugin.mockImplementation(async (_input, options) => {
      options?.onTaskUpdate?.({
        createdAt: 1,
        id: "previous-install-task",
        installSourceLabel: "官方包体 (R2)",
        kind: "plugin-install",
        logs: ["previous install log"],
        message: "Previous install completed",
        packageSha256: "abcdef1234567890",
        packageSource: "r2",
        packageStatus: "installed",
        phase: "completed",
        progress: 1,
        status: "succeeded",
        title: "Plugin install",
        updatedAt: 2,
      });
      return plainPlugin;
    });
    mockGetAppUpdateInfo.mockResolvedValue({ repo: "RachelForster/Shinsekai", version: "0.3.0" });
    mockListAppUpdateTags.mockResolvedValue(["v0.3.1"]);
    mockListPluginCatalog.mockResolvedValue([]);
    mockListPlugins.mockResolvedValue([configurablePlugin, plainPlugin, unloadedPlugin]);
    mockListRepoTags.mockResolvedValue([]);
    mockOpenExternal.mockResolvedValue(undefined);
    mockRunAppUpdate.mockImplementation(async (_input, options?: TaskProgressOptions<unknown>) => {
      options?.onTaskUpdate?.({
        createdAt: 1,
        id: "app-update-task",
        kind: "app-update",
        logs: ["checked out tag"],
        message: "Updated from selected ref",
        phase: "completed",
        progress: 1,
        status: "succeeded",
        title: "App update",
        updatedAt: 2,
      });
      return { message: "Update ready" };
    });
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

  it("opens plugin configuration from route state", async () => {
    renderPage([{ pathname: "/settings/plugins", state: { pluginId: "configurable" } }]);

    expect(await screen.findByText("Dynamic detail description")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dynamic Group" })).toBeInTheDocument();
    expect(mockGetPluginUiDetail).toHaveBeenCalledTimes(1);
  });

  it("opens the requested plugin page and returns to Chat", async () => {
    mockGetPluginUiDetail.mockResolvedValue({ pages: [detailPage, phonePage], plugin: configurablePlugin });
    renderPage(
      [
        {
          pathname: "/settings/plugins",
          state: {
            pageId: "phone",
            pluginId: "configurable",
            returnTo: { pathname: "/chat-stage", search: "?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787" },
          },
        },
      ],
      true,
    );

    expect(await screen.findByText("Phone panel")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Phone controls" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to plugins" }));

    await waitFor(() => expect(screen.getByLabelText("location")).toHaveTextContent("/chat-stage"));
  });

  it("returns plugin configuration to the route it came from", async () => {
    renderPage(
      [
        {
          pathname: "/settings/plugins",
          state: {
            pluginId: "configurable",
            returnTo: { pathname: "/settings/onboarding", state: { activeStep: "plugins" } },
          },
        },
      ],
      true,
    );

    expect(await screen.findByText("Dynamic detail description")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to plugins" }));

    await waitFor(() => expect(screen.getByLabelText("location")).toHaveTextContent("/settings/onboarding"));
    expect(screen.getByLabelText("location")).toHaveTextContent('"activeStep":"plugins"');
  });

  it("does not reopen consumed route-state configuration after returning to the plugin list", async () => {
    renderPage([{ pathname: "/settings/plugins", state: { pluginId: "configurable" } }]);

    expect(await screen.findByText("Dynamic detail description")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to plugins" }));

    await waitFor(() => expect(screen.queryByText("Dynamic detail description")).not.toBeInTheDocument());
    expect(await findPluginCard("Configurable Plugin")).toBeInTheDocument();
    expect(mockGetPluginUiDetail).toHaveBeenCalledTimes(1);
  });

  it("opens the local plugin publisher dialog from the page actions", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Submit plugin" }));

    expect(screen.getByRole("heading", { name: "Submit plugin to market" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read metadata" })).toBeInTheDocument();
  });

  it("opens the plugin developer documentation from the page header", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Developer docs" }));

    expect(mockOpenExternal).toHaveBeenCalledWith("https://plugins.shinsekai.studio/docs/plugin");
  });

  it("uses the installed manifest title as the primary name and the registry name as the secondary name", async () => {
    const installedPlugin = {
      ...plainPlugin,
      entry: "plugins.playwright_browser.plugin:PlaywrightBrowserPlugin",
      id: "com.shinsekai.playwright_browser",
      title: "playwright browser",
      version: "0.1.0",
    };
    mockListPlugins.mockResolvedValue([installedPlugin]);
    mockListPluginCatalog.mockResolvedValue([
      {
        ...catalogItem,
        displayName: "playwright_browser",
        entry: installedPlugin.entry,
        name: "playwright_browser",
        version: "0.1.0",
      },
    ]);

    renderPage();

    const card = await findPluginCard("playwright browser");
    expect(card.querySelector(".plugin-card__title strong")).toHaveTextContent("playwright browser");
    expect(card.querySelector(".plugin-card__title .inline-status")).toHaveTextContent("playwright_browser");
    expect(within(card).getByText("Version 0.1.0")).toBeInTheDocument();
  });

  it("uses raw registry display_name as the discovery card title when the bridge has not camel-cased it", async () => {
    mockListPlugins.mockResolvedValue([]);
    mockListPluginCatalog.mockResolvedValue([
      {
        ...catalogItem,
        displayName: undefined,
        display_name: "Moondream Vision",
        name: "moondream_vision",
      } as PluginCatalogItem & { display_name: string },
    ]);

    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Discover" }));

    expect(await screen.findByRole("heading", { name: "Moondream Vision" })).toBeInTheDocument();
    expect(screen.getByText("moondream_vision")).toBeInTheDocument();
    expect(screen.getByText("Version 0.2.0")).toBeInTheDocument();
  });

  it("opens the shared install dialog for installed-plugin updates and clears the previous completed task", async () => {
    const installedPlugin = {
      ...plainPlugin,
      entry: "plugins.registry_display.plugin:RegistryDisplayPlugin",
      id: "registry_display",
      title: "Registry Display",
      version: "preview",
    };
    mockListPlugins.mockResolvedValue([installedPlugin]);
    mockListPluginCatalog.mockResolvedValue([{ ...catalogItem, entry: installedPlugin.entry, installed: true }]);

    renderPage();

    fireEvent.click(await within(await findPluginCard("Registry Display")).findByRole("button", { name: /Update to/ }));
    expect(await screen.findByRole("heading", { name: "Choose plugin version" })).toBeInTheDocument();
    expect(mockInstallPlugin).not.toHaveBeenCalled();

    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Choose plugin version" })).getByRole("button", { name: "Update" }),
    );
    await waitFor(() => expect(mockInstallPlugin).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Previous install completed")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByText("Previous install completed")).not.toBeInTheDocument());

    fireEvent.click(await within(await findPluginCard("Registry Display")).findByRole("button", { name: /Update to/ }));
    expect(await screen.findByRole("heading", { name: "Choose plugin version" })).toBeInTheDocument();
    expect(screen.queryByText("Previous install completed")).not.toBeInTheDocument();
  });

  it("does not show an update when the installed package hash matches the catalog package", async () => {
    const installedPlugin = {
      ...plainPlugin,
      entry: "plugins.registry_display.plugin:RegistryDisplayPlugin",
      id: "registry_display",
      install: {
        packageSha256: "abcdef1234567890",
        sourceType: "official-package",
      },
      title: "Registry Display",
      version: "0.1.0",
    };
    mockListPlugins.mockResolvedValue([installedPlugin]);
    mockListPluginCatalog.mockResolvedValue([
      { ...catalogItem, entry: installedPlugin.entry, installed: true, version: "0.2.0" },
    ]);

    renderPage();

    const card = await findPluginCard("Registry Display");
    expect(within(card).queryByRole("button", { name: /Update to/ })).toBeNull();
  });

  it("does not show an update action on the discover card when the installed package hash matches", async () => {
    const installedPlugin = {
      ...plainPlugin,
      entry: "plugins.registry_display.plugin:RegistryDisplayPlugin",
      id: "registry_display",
      install: {
        packageSha256: "abcdef1234567890",
        sourceType: "official-package",
      },
      title: "Registry Display",
      version: "0.1.0",
    };
    mockListPlugins.mockResolvedValue([installedPlugin]);
    mockListPluginCatalog.mockResolvedValue([
      {
        ...catalogItem,
        downloaded: true,
        entry: installedPlugin.entry,
        installed: true,
        version: "0.2.0",
      },
    ]);

    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Discover" }));

    const card = (await screen.findByRole("heading", { name: "Registry Display" })).closest(
      ".plugin-market-card",
    ) as HTMLElement;
    expect(within(card).queryByRole("button", { name: "Update" })).toBeNull();
    expect(within(card).getByRole("button", { name: "Installed" })).toBeDisabled();
  });

  it("shows an update action on the discover card when the installed package hash differs", async () => {
    const installedPlugin = {
      ...plainPlugin,
      entry: "plugins.registry_display.plugin:RegistryDisplayPlugin",
      id: "registry_display",
      install: {
        packageSha256: "old-package-sha",
        sourceType: "official-package",
      },
      title: "Registry Display",
      version: "0.2.0",
    };
    mockListPlugins.mockResolvedValue([installedPlugin]);
    mockListPluginCatalog.mockResolvedValue([
      {
        ...catalogItem,
        downloaded: true,
        entry: installedPlugin.entry,
        installed: true,
        version: "0.2.0",
      },
    ]);

    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Discover" }));

    const card = (await screen.findByRole("heading", { name: "Registry Display" })).closest(
      ".plugin-market-card",
    ) as HTMLElement;
    fireEvent.click(await within(card).findByRole("button", { name: "Update" }));

    expect(await screen.findByRole("heading", { name: "Choose plugin version" })).toBeInTheDocument();
  });

  it("shows an update when the catalog package hash differs even if the version did not change", async () => {
    const installedPlugin = {
      ...plainPlugin,
      entry: "plugins.registry_display.plugin:RegistryDisplayPlugin",
      id: "registry_display",
      install: {
        packageSha256: "old-package-sha",
        sourceType: "official-package",
      },
      title: "Registry Display",
      version: "0.2.0",
    };
    mockListPlugins.mockResolvedValue([installedPlugin]);
    mockListPluginCatalog.mockResolvedValue([
      { ...catalogItem, entry: installedPlugin.entry, installed: true, version: "0.2.0" },
    ]);

    renderPage();

    const card = await findPluginCard("Registry Display");
    expect(await within(card).findByRole("button", { name: /Update to/ })).toBeInTheDocument();
  });

  it("renders rich discovery metadata, opens links, and installs an official package", async () => {
    mockListPlugins.mockResolvedValue([]);
    mockListPluginCatalog.mockResolvedValue([
      {
        ...catalogItem,
        logo: "https://example.invalid/logo.png",
        packageSha256: "1234567890abcdef",
        packageSize: 2048,
        securityScan: { static: { pass: true }, secrets: { pass: false } },
        socialLink: "https://example.invalid/author",
        tags: ["browser", "vision", "tools", "agent", "automation"],
        trustLevel: "verified",
        verified: true,
      },
    ]);

    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Discover" }));

    const card = (await screen.findByRole("heading", { name: "Registry Display" })).closest(
      ".plugin-market-card",
    ) as HTMLElement;
    expect(within(card).getByText("Verified")).toBeInTheDocument();
    expect(within(card).getByText("Scan passed")).toBeInTheDocument();
    expect(within(card).getByText("Supports >=0.2.0")).toBeInTheDocument();
    expect(within(card).getByText("+1")).toBeInTheDocument();
    expect(within(card).getByText("2.0 KB")).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "Registry Author" }));
    fireEvent.click(within(card).getByRole("button", { name: "GitHub" }));
    expect(mockOpenExternal).toHaveBeenCalledWith("https://example.invalid/author");
    expect(mockOpenExternal).toHaveBeenCalledWith("https://github.com/owner/registry-display");

    fireEvent.click(within(card).getByRole("button", { name: "Install" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose plugin version" });
    expect(within(dialog).getByText("R2")).toBeInTheDocument();
    expect(within(dialog).getByText("1234567890...")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Install" }));
    await waitFor(() =>
      expect(mockInstallPlugin).toHaveBeenCalledWith(
        expect.objectContaining({
          overwrite: false,
          refKind: "latest",
          source: "registry-display",
        }),
        expect.any(Object),
      ),
    );
  });

  it("reloads the plugin service after installing a plugin on desktop", async () => {
    mockIsTauriDesktop.mockReturnValue(true);
    mockListPlugins.mockResolvedValue([]);
    mockListPluginCatalog.mockResolvedValue([catalogItem]);

    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Discover" }));
    const card = (await screen.findByRole("heading", { name: "Registry Display" })).closest(
      ".plugin-market-card",
    ) as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Install" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose plugin version" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Install" }));

    await waitFor(() => expect(mockInstallPlugin).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockReloadPluginService).toHaveBeenCalledTimes(1));
  });

  it("surfaces a reload failure after install instead of reporting success", async () => {
    mockIsTauriDesktop.mockReturnValue(true);
    mockReloadPluginService.mockRejectedValue(new Error("bridge restart failed"));
    mockListPlugins.mockResolvedValue([]);
    mockListPluginCatalog.mockResolvedValue([catalogItem]);

    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Discover" }));
    const card = (await screen.findByRole("heading", { name: "Registry Display" })).closest(
      ".plugin-market-card",
    ) as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Install" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose plugin version" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Install" }));

    expect(await screen.findByText(/bridge restart failed/)).toBeInTheDocument();
    expect(screen.queryByText("Plugin installed")).not.toBeInTheDocument();
  });

  it("installs a repository catalog plugin from a selected tag", async () => {
    mockListPlugins.mockResolvedValue([]);
    mockListRepoTags.mockResolvedValue(["v1.2.0", "v1.1.0"]);
    mockListPluginCatalog.mockResolvedValue([
      {
        ...catalogItem,
        displayName: "Git Plugin",
        downloadUrl: undefined,
        id: "git-plugin",
        name: "git_plugin",
        packageUrl: undefined,
        repo: "owner/git-plugin",
        trustLevel: "pending_review",
        verified: false,
      },
    ]);

    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Discover" }));
    const card = (await screen.findByRole("heading", { name: "Git Plugin" })).closest(
      ".plugin-market-card",
    ) as HTMLElement;

    fireEvent.click(within(card).getByRole("button", { name: "Install" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose plugin version" });
    expect(await within(dialog).findByText("Repository: owner/git-plugin")).toBeInTheDocument();
    expect(within(dialog).getByText("Pending review")).toBeInTheDocument();
    expect(within(dialog).getByText(/current version or commit is still waiting for review/)).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Version"), { target: { value: "tag:v1.2.0" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Install" }));

    await waitFor(() =>
      expect(mockInstallPlugin).toHaveBeenCalledWith(
        expect.objectContaining({
          overwrite: false,
          refKind: "tag",
          source: "owner/git-plugin",
          tagName: "v1.2.0",
        }),
        expect.any(Object),
      ),
    );
  });

  it("runs an app update from a selected tag in the discovery panel", async () => {
    mockListPlugins.mockResolvedValue([]);
    mockListPluginCatalog.mockResolvedValue([catalogItem]);

    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Discover" }));
    fireEvent.click(await screen.findByRole("button", { name: "Update app" }));

    const dialog = await screen.findByRole("dialog", { name: "Update application" });
    expect(within(dialog).getByText("Repository: RachelForster/Shinsekai")).toBeInTheDocument();
    expect(await within(dialog).findByText("v0.3.1")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Version"), { target: { value: "tag:v0.3.1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Update" }));

    await waitFor(() =>
      expect(mockRunAppUpdate).toHaveBeenCalledWith({ refKind: "tag", tagName: "v0.3.1" }, expect.any(Object)),
    );
    expect(await screen.findByText("Updated from selected ref")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Update application" })).not.toBeInTheDocument());
    expect(screen.getByText("Updated from selected ref")).toBeInTheDocument();
  });
});
