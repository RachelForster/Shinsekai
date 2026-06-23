import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { OnboardingPage } from "../../../features/onboarding/OnboardingPage";
import { onboardingCopy } from "../../../features/onboarding/onboardingCopy";
import { BackgroundSetupPanel } from "../../../features/onboarding/steps/BackgroundSetupPanel";
import { CharacterSetupPanel } from "../../../features/onboarding/steps/CharacterSetupPanel";
import { CompletionSetupPanel } from "../../../features/onboarding/steps/CompletionSetupPanel";
import { PluginSetupPanel } from "../../../features/onboarding/steps/PluginSetupPanel";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({
  downloadTtsBundle: vi.fn(),
  fetchLlmModels: vi.fn(),
  getAppConfig: vi.fn(),
  getTtsBundleRecommendation: vi.fn(),
  importBackgrounds: vi.fn(),
  importCharacters: vi.fn(),
  installMissingRuntimeDependency: vi.fn(),
  installPlugin: vi.fn(),
  isTauriDesktop: vi.fn(),
  listBackgrounds: vi.fn(),
  listCharacters: vi.fn(),
  listPluginCatalog: vi.fn(),
  listPlugins: vi.fn(),
  openExternal: vi.fn(),
  reloadPluginService: vi.fn(),
  saveApiConfig: vi.fn(),
  testLlmConnection: vi.fn(),
  writeDesktopRestartDebugLog: vi.fn(),
}));

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  downloadTtsBundle: (...args: unknown[]) => mocks.downloadTtsBundle(...args),
  fetchLlmModels: (...args: unknown[]) => mocks.fetchLlmModels(...args),
  getAppConfig: () => mocks.getAppConfig(),
  getTtsBundleRecommendation: (...args: unknown[]) => mocks.getTtsBundleRecommendation(...args),
  saveApiConfig: (...args: unknown[]) => mocks.saveApiConfig(...args),
  testLlmConnection: (...args: unknown[]) => mocks.testLlmConnection(...args),
  ttsBundleRecommendationQueryKey: ["tts", "bundleRecommendation"],
}));

vi.mock("../../../entities/chat/repository", () => ({
  installMissingRuntimeDependency: (...args: unknown[]) => mocks.installMissingRuntimeDependency(...args),
}));

vi.mock("../../../entities/plugin/repository", () => ({
  installPlugin: (...args: unknown[]) => mocks.installPlugin(...args),
  listPluginCatalog: () => mocks.listPluginCatalog(),
  listPlugins: () => mocks.listPlugins(),
  pluginCatalogQueryKey: ["plugins", "catalog"],
  pluginsQueryKey: ["plugins"],
}));

vi.mock("../../../entities/files/repository", () => ({
  openExternal: (url: string) => mocks.openExternal(url),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  importCharacters: (files: File[]) => mocks.importCharacters(files),
  listCharacters: () => mocks.listCharacters(),
}));

vi.mock("../../../entities/background/repository", () => ({
  backgroundsQueryKey: ["backgrounds"],
  importBackgrounds: (files: File[]) => mocks.importBackgrounds(files),
  listBackgrounds: () => mocks.listBackgrounds(),
}));

vi.mock("../../../shared/desktop/desktopApi", () => ({
  desktopRestartErrorMessage: (error: unknown) => (error instanceof Error ? error.message : String(error)),
  isDesktopBridgeConnectionError: () => false,
  isTauriDesktop: () => mocks.isTauriDesktop(),
  writeDesktopRestartDebugLog: (...args: unknown[]) => mocks.writeDesktopRestartDebugLog(...args),
}));

vi.mock("../../../features/plugin-manager/pluginReload", () => ({
  reloadPluginService: () => mocks.reloadPluginService(),
}));

const visualCatalogItem = {
  author: "Preview",
  description: "vision screen image assistant",
  downloaded: false,
  entry: "vision.plugin:VisionPlugin",
  id: "vision-plugin",
  installed: false,
  name: "Vision Plugin",
  repo: "example/vision",
  tags: ["vision", "screen"],
};

const browserCatalogItem = {
  author: "Preview",
  description: "playwright browser control",
  downloaded: false,
  entry: "browser.plugin:BrowserPlugin",
  id: "browser-plugin",
  installed: false,
  name: "Browser Plugin",
  repo: "example/browser",
  tags: ["playwright", "browser"],
};

const voiceCatalogItem = {
  author: "Preview",
  description: "whisper voice microphone input",
  downloaded: false,
  entry: "voice.plugin:VoicePlugin",
  id: "voice-plugin",
  installed: false,
  name: "Voice Plugin",
  repo: "example/voice",
  tags: ["voice", "whisper"],
};

const installedPlugin = {
  author: "Preview",
  description: "Installed plugin",
  directory: "plugins/vision",
  enabled: true,
  entry: "vision.plugin:VisionPlugin",
  id: "vision-plugin",
  loaded: true,
  permissions: ["settings"],
  settingsPages: ["Vision settings"],
  slots: ["settings-extension" as const],
  title: "Vision Plugin",
  toolsTabs: [],
  version: "1.0.0",
};

function createClient() {
  return new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
}

function renderWithProviders(children: React.ReactNode, initialPath = "/onboarding") {
  return render(
    <QueryClientProvider client={createClient()}>
      <ToastProvider>
        <I18nProvider language="en">
          <MemoryRouter initialEntries={[initialPath]}>{children}</MemoryRouter>
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("onboarding flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getAppConfig.mockResolvedValue(structuredClone(sampleConfig));
    mocks.getTtsBundleRecommendation.mockResolvedValue({ gpus: [], kind: "gptso", platform: "Preview" });
    mocks.fetchLlmModels.mockResolvedValue([]);
    mocks.testLlmConnection.mockResolvedValue(undefined);
    mocks.saveApiConfig.mockImplementation(async (input) => input);
    mocks.downloadTtsBundle.mockResolvedValue({ path: "/tmp/gpt-sovits", provider: "gpt-sovits" });
    mocks.listPluginCatalog.mockResolvedValue([visualCatalogItem, browserCatalogItem, voiceCatalogItem]);
    mocks.listPlugins.mockResolvedValue([]);
    mocks.installMissingRuntimeDependency.mockImplementation(async (_input, options) => {
      options?.onTaskUpdate?.({ message: "dependency", phase: "completed", progress: 1, status: "succeeded" });
      return { message: "installed", moduleName: "openai", packageName: "openai", pipCode: 0, pipOutput: "" };
    });
    mocks.installPlugin.mockImplementation(async (source, options) => {
      options?.onTaskUpdate?.({ message: "plugin", phase: "completed", progress: 1, status: "succeeded" });
      return { ...installedPlugin, id: String(source).includes("browser") ? "browser-plugin" : "vision-plugin" };
    });
    mocks.isTauriDesktop.mockReturnValue(false);
    mocks.reloadPluginService.mockResolvedValue(undefined);
    mocks.listCharacters.mockResolvedValue([]);
    mocks.listBackgrounds.mockResolvedValue([]);
    mocks.importCharacters.mockResolvedValue([{ name: "Imported Nanami" }]);
    mocks.importBackgrounds.mockResolvedValue([{ name: "Imported Room" }]);
  });

  it("guards unsaved optional steps and finishes through the guided flow", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/settings/templates" element={<div>Templates destination</div>} />
      </Routes>,
    );

    expect(await screen.findByRole("heading", { name: "First run guide" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open next step" }));

    const apiDialog = await screen.findByRole("dialog", { name: "Confirm" });
    expect(apiDialog).toHaveTextContent("Skip anyway?");
    fireEvent.click(within(apiDialog).getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("heading", { name: "Common plugins" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open next step" }));
    const pluginDialog = await screen.findByRole("dialog", { name: "Confirm" });
    expect(pluginDialog).toHaveTextContent("No plugins have been installed yet");
    fireEvent.click(within(pluginDialog).getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("heading", { name: "Common plugins" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open next step" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Confirm" })).getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Characters")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Backgrounds\b/ }));
    expect(await screen.findByText(/Skipping background import is fine/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Ready\b/ }));
    fireEvent.click(screen.getAllByRole("button", { name: "Open templates" })[0]);
    expect(await screen.findByText("Templates destination")).toBeInTheDocument();
  });

  it("installs selected plugin presets and exposes configuration after reload", async () => {
    const onInstalled = vi.fn();
    mocks.listPlugins.mockImplementation(async () => [
      { ...installedPlugin, id: "vision-plugin", title: "Vision Plugin" },
      {
        ...installedPlugin,
        entry: "browser.plugin:BrowserPlugin",
        id: "browser-plugin",
        title: "Browser Plugin",
        toolsTabs: ["Browser tools"],
      },
      {
        ...installedPlugin,
        entry: "voice.plugin:VoicePlugin",
        id: "voice-plugin",
        settingsPages: [],
        title: "Voice Plugin",
      },
    ]);

    renderWithProviders(<PluginSetupPanel copy={onboardingCopy.en} onInstalled={onInstalled} />);

    expect(await screen.findByText("Visual plugin")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "One-click download" }));

    await waitFor(() => expect(mocks.installMissingRuntimeDependency).toHaveBeenCalled());
    await waitFor(() => expect(mocks.installPlugin).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(onInstalled).toHaveBeenCalledTimes(1));
    expect(await screen.findAllByRole("button", { name: "Configure" })).toHaveLength(3);
    expect(screen.getByText(/Dependencies and selected plugins are installed/)).toBeInTheDocument();
  });

  it("imports characters and backgrounds and opens resource links", async () => {
    const characterView = renderWithProviders(<CharacterSetupPanel copy={onboardingCopy.en} />);

    expect(await screen.findByText("No characters yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open resource library" }));
    expect(mocks.openExternal).toHaveBeenCalled();

    const characterInput = characterView.container.querySelector<HTMLInputElement>('input[type="file"]');
    const characterFile = new File(["char"], "nanami.char");
    fireEvent.change(characterInput!, { target: { files: [characterFile] } });
    await waitFor(() => expect(mocks.importCharacters).toHaveBeenCalledWith([characterFile]));
    characterView.unmount();

    const backgroundView = renderWithProviders(<BackgroundSetupPanel copy={onboardingCopy.en} />);
    expect(await screen.findByText("No backgrounds yet.")).toBeInTheDocument();
    const backgroundInput = backgroundView.container.querySelector<HTMLInputElement>('input[type="file"]');
    const backgroundFile = new File(["bg"], "room.bg");
    fireEvent.change(backgroundInput!, { target: { files: [backgroundFile] } });
    await waitFor(() => expect(mocks.importBackgrounds).toHaveBeenCalledWith([backgroundFile]));
    expect(screen.getByText(/Skipping background import is fine/)).toBeInTheDocument();
  });

  it("opens templates from the completion panel action", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/onboarding" element={<CompletionSetupPanel copy={onboardingCopy.en} />} />
        <Route path="/settings/templates" element={<div>Templates destination</div>} />
      </Routes>,
    );

    expect(screen.getByText("Setup complete. Time to chat.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open templates" }));
    expect(await screen.findByText("Templates destination")).toBeInTheDocument();
  });
});
