import { lazy, Suspense, useState } from "react";
import { Outlet } from "react-router-dom";

import { SidebarNav } from "./SidebarNav";
import { StartupUpdatePrompt } from "./StartupUpdatePrompt";

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
      <StartupUpdatePrompt />
    </div>
  );
}
