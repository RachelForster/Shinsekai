import { render, screen, waitFor } from "@testing-library/react";
import { Outlet, MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../app/routes/AppRoutes";

vi.mock("../../../app/shell/AppShell", () => ({
  AppShell: () => (
    <section aria-label="settings shell">
      <Outlet />
    </section>
  ),
}));

vi.mock("../../../features/api-settings/ApiSettingsPage", () => ({
  ApiSettingsPage: () => <h1>API settings route</h1>,
}));

vi.mock("../../../features/background-manager/BackgroundManagerPage", () => ({
  BackgroundManagerPage: () => <h1>Backgrounds route</h1>,
}));

vi.mock("../../../features/effect-manager/EffectManagerPage", () => ({
  EffectManagerPage: () => <h1>Effects route</h1>,
}));

vi.mock("../../../features/character-editor/CharacterEditorPage", () => ({
  CharacterEditorPage: () => <h1>Characters route</h1>,
}));

vi.mock("../../../features/chat-launcher/ChatLauncherPage", () => ({
  ChatLauncherPage: () => <h1>Launch route</h1>,
}));

vi.mock("../../../features/chat-stage/ChatStagePage", () => ({
  ChatStagePage: () => <h1>Chat stage route</h1>,
}));

vi.mock("../../../features/chat-stage/theme/ChatThemeManagementPage", () => ({
  ChatThemeManagementPage: () => <h1>Chat themes route</h1>,
}));

vi.mock("../../../features/logs/LogsPage", () => ({
  LogsPage: () => <h1>Logs route</h1>,
}));

vi.mock("../../../features/music-cover/MusicCoverPage", () => ({
  MusicCoverPage: () => <h1>Music cover route</h1>,
}));

vi.mock("../../../features/onboarding/OnboardingPage", () => ({
  OnboardingPage: () => <h1>Onboarding route</h1>,
}));

vi.mock("../../../features/plugin-manager/PluginManagerPage", () => ({
  PluginManagerPage: () => <h1>Plugins route</h1>,
}));

vi.mock("../../../features/system-settings/SystemSettingsPage", () => ({
  SystemSettingsPage: () => <h1>System route</h1>,
}));

vi.mock("../../../features/template-editor/TemplateEditorPage", () => ({
  TemplateEditorPage: () => <h1>Templates route</h1>,
}));

vi.mock("../../../features/tools/ToolsPage", () => ({
  ToolsPage: () => <h1>Tools route</h1>,
}));

vi.mock("../../../features/onboarding/onboardingState", () => ({
  getInitialSettingsPath: () => "/settings/api",
}));

function renderRoute(path: string) {
  return render(
    <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }} initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("AppRoutes", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    ["/settings/onboarding", "Onboarding route"],
    ["/settings/api", "API settings route"],
    ["/settings/characters", "Characters route"],
    ["/settings/backgrounds", "Backgrounds route"],
    ["/settings/effects", "Effects route"],
    ["/settings/templates", "Templates route"],
    ["/settings/plugins", "Plugins route"],
    ["/settings/logs", "Logs route"],
    ["/settings/tools", "Tools route"],
    ["/settings/music-cover", "Music cover route"],
    ["/settings/launch", "Launch route"],
    ["/settings/system", "System route"],
    ["/settings/system/chat-themes", "Chat themes route"],
    ["/chat", "Chat stage route"],
    ["/chat-stage", "Chat stage route"],
  ])("renders %s", async (path, heading) => {
    renderRoute(path);

    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it.each(["/settings", "/unknown"])("redirects %s to the initial settings path", async (path) => {
    renderRoute(path);

    await waitFor(() => expect(screen.getByRole("heading", { name: "API settings route" })).toBeInTheDocument());
  });
});
