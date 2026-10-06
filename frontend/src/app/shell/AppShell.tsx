import { lazy, Suspense, useState } from "react";
import { Outlet } from "react-router-dom";

import { FeatureHighlightsPrompt } from "../../features/release-highlights/FeatureHighlightsPrompt";
import { SidebarNav } from "./SidebarNav";
import { StartupUpdatePrompt, type StartupUpdatePromptState } from "./StartupUpdatePrompt";

const AgentDrawer = lazy(() =>
  import("../../features/agent/AgentDrawer").then(({ AgentDrawer }) => ({
    default: AgentDrawer,
  })),
);

function DrawerFallback() {
  return <div aria-hidden className="agent-drawer-fallback" />;
}

export function AppShell() {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantMounted, setAssistantMounted] = useState(false);
  const [startupUpdateState, setStartupUpdateState] = useState<StartupUpdatePromptState>({
    checkComplete: false,
    open: false,
  });

  return (
    <div className="app-shell">
      <SidebarNav
        onAssistantToggle={() => {
          setAssistantMounted(true);
          setAssistantOpen((open) => !open);
        }}
        assistantOpen={assistantOpen}
      />
      <main className="content-outlet">
        <Outlet />
      </main>
      {assistantMounted ? (
        <Suspense fallback={<DrawerFallback />}>
          <AgentDrawer onClose={() => setAssistantOpen(false)} open={assistantOpen} />
        </Suspense>
      ) : null}
      <StartupUpdatePrompt onStateChange={setStartupUpdateState} />
      <FeatureHighlightsPrompt enabled={startupUpdateState.checkComplete && !startupUpdateState.open} />
    </div>
  );
}
