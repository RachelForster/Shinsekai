import { Navigate, Route, Routes, HashRouter } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { ApiSettingsPage } from "../../features/api-settings/ApiSettingsPage";
import { BackgroundManagerPage } from "../../features/background-manager/BackgroundManagerPage";
import { CharacterEditorPage } from "../../features/character-editor/CharacterEditorPage";
import { ChatLauncherPage } from "../../features/chat-launcher/ChatLauncherPage";
import { ChatStagePage } from "../../features/chat-stage/ChatStagePage";
import { MusicCoverPage } from "../../features/music-cover/MusicCoverPage";
import { PluginManagerPage } from "../../features/plugin-manager/PluginManagerPage";
import { SystemSettingsPage } from "../../features/system-settings/SystemSettingsPage";
import { TemplateEditorPage } from "../../features/template-editor/TemplateEditorPage";
import { ToolsPage } from "../../features/tools/ToolsPage";

export function AppRoutes() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<AppShell />} path="/settings">
          <Route element={<Navigate replace to="/settings/api" />} index />
          <Route element={<ApiSettingsPage />} path="api" />
          <Route element={<CharacterEditorPage />} path="characters" />
          <Route element={<BackgroundManagerPage />} path="backgrounds" />
          <Route element={<TemplateEditorPage />} path="templates" />
          <Route element={<PluginManagerPage />} path="plugins" />
          <Route element={<ToolsPage />} path="tools" />
          <Route element={<MusicCoverPage />} path="music-cover" />
          <Route element={<ChatLauncherPage />} path="launch" />
          <Route element={<SystemSettingsPage />} path="system" />
        </Route>
        <Route element={<ChatStagePage />} path="/chat" />
        <Route element={<Navigate replace to="/settings/api" />} path="*" />
      </Routes>
    </HashRouter>
  );
}
