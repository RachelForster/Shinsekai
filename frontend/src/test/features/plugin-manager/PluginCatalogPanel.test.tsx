import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PluginCatalogInstallDialog, PluginCatalogPanel } from "../../../features/plugin-manager/PluginCatalogPanel";
import type { PluginCatalogItem } from "../../../entities/plugin/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const repoMocks = vi.hoisted(() => ({
  getAppUpdateInfo: vi.fn(),
  installPlugin: vi.fn(),
  listAppUpdateTags: vi.fn(),
  listPluginCatalog: vi.fn(),
  listRepoTags: vi.fn(),
  runAppUpdate: vi.fn(),
}));

const fileMocks = vi.hoisted(() => ({
  openExternal: vi.fn(),
}));

const desktopMocks = vi.hoisted(() => ({
  checkDesktopUpdate: vi.fn(),
  installDesktopUpdate: vi.fn(),
  isDesktopBridgeConnectionError: vi.fn(),
  isTauriDesktop: vi.fn(),
  onDesktopUpdateProgress: vi.fn(),
}));

vi.mock("../../../entities/plugin/repository", () => ({
  getAppUpdateInfo: () => repoMocks.getAppUpdateInfo(),
  installPlugin: (...args: unknown[]) => repoMocks.installPlugin(...args),
  listAppUpdateTags: () => repoMocks.listAppUpdateTags(),
  listPluginCatalog: () => repoMocks.listPluginCatalog(),
  listRepoTags: (repo: string) => repoMocks.listRepoTags(repo),
  runAppUpdate: (...args: unknown[]) => repoMocks.runAppUpdate(...args),
}));

vi.mock("../../../entities/files/repository", () => ({
  openExternal: (url: string) => fileMocks.openExternal(url),
}));

vi.mock("../../../shared/desktop/desktopApi", () => ({
  checkDesktopUpdate: () => desktopMocks.checkDesktopUpdate(),
  desktopRestartErrorMessage: (error: unknown) => (error instanceof Error ? error.message : String(error || "")),
  installDesktopUpdate: () => desktopMocks.installDesktopUpdate(),
  isDesktopBridgeConnectionError: (error: unknown) => desktopMocks.isDesktopBridgeConnectionError(error),
  isTauriDesktop: () => desktopMocks.isTauriDesktop(),
  onDesktopUpdateProgress: (listener: unknown) => desktopMocks.onDesktopUpdateProgress(listener),
}));

const officialPlugin: PluginCatalogItem = {
  author: "Alice",
  description: "Official package plugin",
  displayName: "Official Demo",
  downloaded: false,
  entry: "official.plugin:Demo",
  id: "official-demo",
  installed: false,
  lowestShinsekaiVersion: "0.2.0",
  name: "official-demo",
  packageR2Key: "plugins/official-demo.zip",
  packageSha256: "abcdef1234567890abcdef",
  packageSize: 1536,
  packageSource: "r2",
  packageUrl: "https://packages.example/official-demo.zip",
  repo: "owner/official-demo",
  securityScan: { bandit: { pass: true } },
  shortDescription: "Official short description",
  socialLink: "https://example.test/alice",
  stars: 1234,
  tags: ["tts", "vision", "safe", "demo", "extra"],
  trustLevel: "verified",
  updatedAt: "2026-06-01T12:00:00Z",
  verified: true,
  version: "v1.2.0",
};

const repoPlugin: PluginCatalogItem = {
  author: "Bob",
  description: "Community repo plugin",
  downloaded: false,
  entry: "repo.plugin:Demo",
  id: "repo-demo",
  installed: false,
  name: "repo-demo",
  repo: "owner/repo-demo",
  shortDescription: "Repo short description",
  stars: 42,
  tags: ["repo"],
  trustLevel: "pending_review",
  updatedAt: "2026-05-20T12:00:00Z",
  version: "0.3.0",
};

function renderWithProviders(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">{children}</I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function fakeMutation(overrides: Record<string, unknown> = {}) {
  return {
    isPending: false,
    isSuccess: false,
    mutate: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  };
}

function fakeCatalogQuery(data: PluginCatalogItem[], overrides: Record<string, unknown> = {}) {
  return {
    data,
    error: null,
    isError: false,
    isLoading: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

function renderPanel({
  appUpdateMutation = fakeMutation(),
  catalogQuery = fakeCatalogQuery([officialPlugin, repoPlugin]),
  getCatalogInstallState = (plugin: PluginCatalogItem) => ({
    downloaded: plugin.id === "repo-demo",
    installed: plugin.id === "repo-demo",
    updateAvailable: plugin.id === "repo-demo",
  }),
  installMutation = fakeMutation(),
  installingSource = "",
  onOpenCatalogInstall = vi.fn(),
}: {
  appUpdateMutation?: ReturnType<typeof fakeMutation>;
  catalogQuery?: ReturnType<typeof fakeCatalogQuery>;
  getCatalogInstallState?: (plugin: PluginCatalogItem) => {
    downloaded: boolean;
    installed: boolean;
    updateAvailable: boolean;
  };
  installMutation?: ReturnType<typeof fakeMutation>;
  installingSource?: string;
  onOpenCatalogInstall?: (plugin: PluginCatalogItem) => void;
} = {}) {
  renderWithProviders(
    <PluginCatalogPanel
      appUpdateMutation={appUpdateMutation as never}
      appUpdateTask={null}
      catalogQuery={catalogQuery as never}
      getCatalogInstallState={getCatalogInstallState}
      installMutation={installMutation as never}
      installingSource={installingSource}
      onOpenCatalogInstall={onOpenCatalogInstall}
    />,
  );
  return { appUpdateMutation, catalogQuery, installMutation, onOpenCatalogInstall };
}

describe("PluginCatalogPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    desktopMocks.isTauriDesktop.mockReturnValue(false);
    desktopMocks.checkDesktopUpdate.mockResolvedValue(null);
    desktopMocks.installDesktopUpdate.mockResolvedValue(undefined);
    desktopMocks.isDesktopBridgeConnectionError.mockReturnValue(false);
    desktopMocks.onDesktopUpdateProgress.mockResolvedValue(() => undefined);
    repoMocks.getAppUpdateInfo.mockResolvedValue({ repo: "RachelForster/Shinsekai", version: "1.0.0" });
    repoMocks.listAppUpdateTags.mockResolvedValue(["v2.0.0"]);
    repoMocks.listRepoTags.mockResolvedValue(["v0.3.0", "v0.2.0"]);
  });

  it("renders catalog metadata, opens links, filters cards, refreshes, and starts install flow", async () => {
    const onOpenCatalogInstall = vi.fn();
    const { catalogQuery } = renderPanel({ onOpenCatalogInstall });

    expect(await screen.findByText("Official Demo")).toBeInTheDocument();
    expect(await screen.findByText("Current version: 1.0.0")).toBeInTheDocument();
    expect(screen.getByText("Version 1.2.0")).toBeInTheDocument();
    expect(screen.getByText("Supports 0.2.0")).toBeInTheDocument();
    expect(screen.getByText("Scan passed")).toBeInTheDocument();
    expect(screen.getByText("1.5 KB")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();

    const officialCard = screen.getByText("Official Demo").closest("article");
    expect(officialCard).toBeInstanceOf(HTMLElement);
    fireEvent.click(within(officialCard as HTMLElement).getByRole("button", { name: "Alice" }));
    fireEvent.click(within(officialCard as HTMLElement).getByRole("button", { name: "GitHub" }));
    expect(fileMocks.openExternal).toHaveBeenCalledWith("https://example.test/alice");
    expect(fileMocks.openExternal).toHaveBeenCalledWith("https://github.com/owner/official-demo");

    fireEvent.click(within(officialCard as HTMLElement).getByRole("button", { name: "Install" }));
    expect(onOpenCatalogInstall).toHaveBeenCalledWith(
      expect.objectContaining({ downloaded: false, id: "official-demo" }),
    );

    fireEvent.change(screen.getByPlaceholderText("Search plugins"), { target: { value: "nothing-here" } });
    expect(await screen.findByText("No matching items")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Search plugins"), { target: { value: "repo" } });
    expect(await screen.findAllByText("repo-demo")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(catalogQuery.refetch).toHaveBeenCalledTimes(1);
  });

  it("runs non-desktop app updates from a selected tag", async () => {
    const appUpdateMutation = fakeMutation();
    renderPanel({ appUpdateMutation });

    await screen.findByText("Official Demo");
    fireEvent.click(screen.getByRole("button", { name: "Update app" }));

    const dialog = await screen.findByRole("dialog", { name: "Update application" });
    await waitFor(() => expect(repoMocks.listAppUpdateTags).toHaveBeenCalledTimes(1));
    fireEvent.click(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "v2.0.0" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Update" }));

    expect(appUpdateMutation.mutate).toHaveBeenCalledWith({ refKind: "tag", tagName: "v2.0.0" });
  });

  it("checks and installs desktop updates through the desktop updater path", async () => {
    desktopMocks.isTauriDesktop.mockReturnValue(true);
    desktopMocks.checkDesktopUpdate.mockResolvedValue({
      body: "Release notes",
      date: "2026-06-20",
      version: "2.0.0",
    });
    renderPanel();

    await screen.findByText("Official Demo");
    fireEvent.click(screen.getByRole("button", { name: "Update app" }));

    const dialog = await screen.findByRole("dialog", { name: "Desktop update" });
    expect(await within(dialog).findByText("Version 2.0.0 is available")).toBeInTheDocument();
    expect(within(dialog).getByText("Published: 2026-06-20")).toBeInTheDocument();
    expect(within(dialog).getAllByText("Release notes")).toHaveLength(2);

    fireEvent.click(within(dialog).getByRole("button", { name: "Install and restart" }));

    await waitFor(() => expect(desktopMocks.installDesktopUpdate).toHaveBeenCalledTimes(1));
    expect(
      await within(dialog).findByText("The update was installed. Restarting the application..."),
    ).toBeInTheDocument();
  });

  it("installs official packages and repo tags from the install dialog", async () => {
    const installMutation = fakeMutation();
    renderWithProviders(
      <PluginCatalogInstallDialog
        installMutation={installMutation as never}
        installTask={null}
        onClose={vi.fn()}
        plugin={officialPlugin}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Choose plugin version" })).toHaveTextContent("SHA256");
    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    expect(installMutation.mutate).toHaveBeenCalledWith({
      overwrite: false,
      refKind: "latest",
      source: "official-demo",
      tagName: undefined,
    });

    installMutation.mutate.mockClear();
    renderWithProviders(
      <PluginCatalogInstallDialog
        installMutation={installMutation as never}
        installTask={null}
        onClose={vi.fn()}
        plugin={repoPlugin}
      />,
    );

    const dialog = screen.getAllByRole("dialog", { name: "Choose plugin version" }).at(-1)!;
    await waitFor(() => expect(repoMocks.listRepoTags).toHaveBeenCalledWith("owner/repo-demo"));
    fireEvent.click(within(dialog).getByRole("combobox"));
    fireEvent.click(await screen.findByRole("option", { name: "v0.3.0" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Install" }));

    expect(installMutation.mutate).toHaveBeenCalledWith({
      overwrite: false,
      refKind: "tag",
      source: "owner/repo-demo",
      tagName: "v0.3.0",
    });
  });

  it("renders loading, empty, and error catalog states", async () => {
    const { rerender } = renderWithProviders(
      <PluginCatalogPanel
        appUpdateMutation={fakeMutation() as never}
        appUpdateTask={null}
        catalogQuery={fakeCatalogQuery([], { isLoading: true }) as never}
        getCatalogInstallState={() => ({ downloaded: false, installed: false, updateAvailable: false })}
        installMutation={fakeMutation() as never}
        installingSource=""
        onOpenCatalogInstall={vi.fn()}
      />,
    );

    expect(await screen.findByText("Loading plugin catalog")).toBeInTheDocument();

    rerender(
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
          })
        }
      >
        <ToastProvider>
          <I18nProvider language="en">
            <PluginCatalogPanel
              appUpdateMutation={fakeMutation() as never}
              appUpdateTask={null}
              catalogQuery={fakeCatalogQuery([]) as never}
              getCatalogInstallState={() => ({ downloaded: false, installed: false, updateAvailable: false })}
              installMutation={fakeMutation() as never}
              installingSource=""
              onOpenCatalogInstall={vi.fn()}
            />
          </I18nProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("No plugins found")).toBeInTheDocument();

    rerender(
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
          })
        }
      >
        <ToastProvider>
          <I18nProvider language="en">
            <PluginCatalogPanel
              appUpdateMutation={fakeMutation() as never}
              appUpdateTask={null}
              catalogQuery={
                fakeCatalogQuery([], {
                  error: new Error("catalog failed"),
                  isError: true,
                }) as never
              }
              getCatalogInstallState={() => ({ downloaded: false, installed: false, updateAvailable: false })}
              installMutation={fakeMutation() as never}
              installingSource=""
              onOpenCatalogInstall={vi.fn()}
            />
          </I18nProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Could not load plugin catalog")).toBeInTheDocument();
  });
});
