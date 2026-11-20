import { lazy, Suspense, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { FeatureHighlightsPrompt } from "../../features/release-highlights/FeatureHighlightsPrompt";
import { MobileTopAppBar } from "./MobileTopAppBar";
import { SidebarNav } from "./SidebarNav";
import { StartupUpdatePrompt, type StartupUpdatePromptState } from "./StartupUpdatePrompt";

const AgentDrawer = lazy(() =>
  import("../../features/agent/AgentDrawer").then(({ AgentDrawer }) => ({
    default: AgentDrawer,
  })),
);

const DECORATE_SUBNAV = {
  ariaLabel: "装扮子导航",
  items: [
    { end: false, label: "背景管理", to: "/settings/backgrounds" },
    { end: false, label: "特效管理", to: "/settings/effects" },
  ],
} as const;

const SYSTEM_SUBNAV = {
  ariaLabel: "系统子导航",
  items: [
    { end: true, label: "系统设置", to: "/settings/system" },
    { end: false, label: "对话主题", to: "/settings/system/chat-themes" },
    { end: false, label: "运行日志", to: "/settings/logs" },
  ],
} as const;

function resolveMobileSubnav(pathname: string) {
  if (pathname.startsWith("/settings/backgrounds") || pathname.startsWith("/settings/effects")) {
    return DECORATE_SUBNAV;
  }
  if (
    pathname.startsWith("/settings/system") ||
    pathname.startsWith("/settings/logs") ||
    pathname.startsWith("/settings/plugins")
  ) {
    return SYSTEM_SUBNAV;
  }
  return null;
}

function DrawerFallback() {
  return <div aria-hidden className="agent-drawer-fallback" />;
}

export function AppShell() {
  const location = useLocation();
  const outletRef = useRef<HTMLElement | null>(null);
  const mobileSubnav = resolveMobileSubnav(location.pathname);
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
      <MobileTopAppBar outletRef={outletRef} />
      <main className="content-outlet" ref={outletRef}>
        {mobileSubnav ? (
          <nav aria-label={mobileSubnav.ariaLabel} className="mobile-subnav">
            {mobileSubnav.items.map((item) => (
              <NavLink className="mobile-subnav__item" end={item.end} key={item.to} to={item.to}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        ) : null}
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
