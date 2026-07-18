import { lazy, Suspense, useState } from "react";
import { Outlet } from "react-router-dom";

import { FeatureHighlightsPrompt } from "../../features/release-highlights/FeatureHighlightsPrompt";
import { SidebarNav } from "./SidebarNav";
import { StartupUpdatePrompt, type StartupUpdatePromptState } from "./StartupUpdatePrompt";

const ToolsDrawer = lazy(() =>
  import("../../features/tools/ToolsDrawer").then(({ ToolsDrawer }) => ({
    default: ToolsDrawer,
  })),
);

function DrawerFallback() {
  return <div aria-hidden className="tools-drawer-fallback" />;
}

export function AppShell() {
  const [toolsOpen, setToolsOpen] = useState(false);
  const [startupUpdateState, setStartupUpdateState] = useState<StartupUpdatePromptState>({
    checkComplete: false,
    open: false,
  });

  return (
    <div className="app-shell">
      <SidebarNav onToolsToggle={() => setToolsOpen((open) => !open)} toolsOpen={toolsOpen} />
      <main className="content-outlet">
        <Outlet />
      </main>
      {toolsOpen ? (
        <Suspense fallback={<DrawerFallback />}>
          <ToolsDrawer onClose={() => setToolsOpen(false)} open={toolsOpen} />
        </Suspense>
      ) : null}
      <StartupUpdatePrompt onStateChange={setStartupUpdateState} />
      <FeatureHighlightsPrompt enabled={startupUpdateState.checkComplete && !startupUpdateState.open} />
    </div>
  );
}
