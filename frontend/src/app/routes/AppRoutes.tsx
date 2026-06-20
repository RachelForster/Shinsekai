import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { getInitialSettingsPath } from "../../features/onboarding/onboardingState";

const ApiSettingsPage = lazy(() =>
  import("../../features/api-settings/ApiSettingsPage").then(({ ApiSettingsPage }) => ({
    default: ApiSettingsPage,
  })),
);
const BackgroundManagerPage = lazy(() =>
  import("../../features/background-manager/BackgroundManagerPage").then(({ BackgroundManagerPage }) => ({
    default: BackgroundManagerPage,
  })),
);
const CharacterEditorPage = lazy(() =>
  import("../../features/character-editor/CharacterEditorPage").then(({ CharacterEditorPage }) => ({
    default: CharacterEditorPage,
  })),
);
const ChatLauncherPage = lazy(() =>
  import("../../features/chat-launcher/ChatLauncherPage").then(({ ChatLauncherPage }) => ({
    default: ChatLauncherPage,
  })),
);
const ChatStagePage = lazy(() =>
  import("../../features/chat-stage/ChatStagePage").then(({ ChatStagePage }) => ({
    default: ChatStagePage,
  })),
);
const LogsPage = lazy(() =>
  import("../../features/logs/LogsPage").then(({ LogsPage }) => ({
    default: LogsPage,
  })),
);
const MusicCoverPage = lazy(() =>
  import("../../features/music-cover/MusicCoverPage").then(({ MusicCoverPage }) => ({
    default: MusicCoverPage,
  })),
);
const OnboardingPage = lazy(() =>
  import("../../features/onboarding/OnboardingPage").then(({ OnboardingPage }) => ({
    default: OnboardingPage,
  })),
);
const PluginManagerPage = lazy(() =>
  import("../../features/plugin-manager/PluginManagerPage").then(({ PluginManagerPage }) => ({
    default: PluginManagerPage,
  })),
);
const SystemSettingsPage = lazy(() =>
  import("../../features/system-settings/SystemSettingsPage").then(({ SystemSettingsPage }) => ({
    default: SystemSettingsPage,
  })),
);
const TemplateEditorPage = lazy(() =>
  import("../../features/template-editor/TemplateEditorPage").then(({ TemplateEditorPage }) => ({
    default: TemplateEditorPage,
  })),
);
const ToolsPage = lazy(() =>
  import("../../features/tools/ToolsPage").then(({ ToolsPage }) => ({
    default: ToolsPage,
  })),
);

function RouteLoader() {
  return <div aria-hidden className="route-loading" />;
}

function LazyRoute({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RouteLoader />}>{children}</Suspense>;
}

function lazyRouteElement(children: ReactNode) {
  return <LazyRoute>{children}</LazyRoute>;
}

function chatStageRouteElement() {
  return lazyRouteElement(<ChatStagePage />);
}

function InitialSettingsRedirect() {
  return <Navigate replace to={getInitialSettingsPath()} />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />} path="/settings">
        <Route element={<InitialSettingsRedirect />} index />
        <Route element={lazyRouteElement(<OnboardingPage />)} path="onboarding" />
        <Route element={lazyRouteElement(<ApiSettingsPage />)} path="api" />
        <Route element={lazyRouteElement(<CharacterEditorPage />)} path="characters" />
        <Route element={lazyRouteElement(<BackgroundManagerPage />)} path="backgrounds" />
        <Route element={lazyRouteElement(<TemplateEditorPage />)} path="templates" />
        <Route element={lazyRouteElement(<PluginManagerPage />)} path="plugins" />
        <Route element={lazyRouteElement(<LogsPage />)} path="logs" />
        <Route element={lazyRouteElement(<ToolsPage />)} path="tools" />
        <Route element={lazyRouteElement(<MusicCoverPage />)} path="music-cover" />
        <Route element={lazyRouteElement(<ChatLauncherPage />)} path="launch" />
        <Route element={lazyRouteElement(<SystemSettingsPage />)} path="system" />
      </Route>
      <Route element={chatStageRouteElement()} path="/chat" />
      <Route element={chatStageRouteElement()} path="/chat-stage" />
      <Route element={<InitialSettingsRedirect />} path="*" />
    </Routes>
  );
}
