import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { FeatureHighlightsPrompt } from "../../features/release-highlights/FeatureHighlightsPrompt";
import { useI18n, type MessageKey } from "../../shared/i18n";
import { isStandaloneRuntimeActive, RUNTIME_MODE_CHANGE_EVENT } from "../../shared/platform/runtimeTarget";
import { MobileTopAppBar } from "./MobileTopAppBar";
import { SidebarNav } from "./SidebarNav";
import { StartupUpdatePrompt, type StartupUpdatePromptState } from "./StartupUpdatePrompt";

const AgentDrawer = lazy(() =>
  import("../../features/agent/AgentDrawer").then(({ AgentDrawer }) => ({
    default: AgentDrawer,
  })),
);

interface MobileSubnavSchema {
  ariaLabelKey: MessageKey;
  items: ReadonlyArray<{
    end: boolean;
    labelKey: MessageKey;
    to: string;
  }>;
}

const DECORATE_SUBNAV: MobileSubnavSchema = {
  ariaLabelKey: "nav.subnav.decorateAria",
  items: [
    { end: false, labelKey: "nav.subnav.backgrounds", to: "/settings/backgrounds" },
    { end: false, labelKey: "nav.subnav.effects", to: "/settings/effects" },
  ],
};

const SYSTEM_SUBNAV: MobileSubnavSchema = {
  ariaLabelKey: "nav.subnav.systemAria",
  items: [
    { end: true, labelKey: "nav.subnav.systemSettings", to: "/settings/system" },
    { end: false, labelKey: "nav.subnav.chatThemes", to: "/settings/system/chat-themes" },
    { end: false, labelKey: "nav.subnav.logs", to: "/settings/logs" },
  ],
};

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
  const { t } = useI18n();
  const location = useLocation();
  const outletRef = useRef<HTMLElement | null>(null);
  const mobileSubnav = resolveMobileSubnav(location.pathname);
  const [standalone, setStandalone] = useState(() => isStandaloneRuntimeActive());
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantMounted, setAssistantMounted] = useState(false);
  const [startupUpdateState, setStartupUpdateState] = useState<StartupUpdatePromptState>({
    checkComplete: false,
    open: false,
  });

  useEffect(() => {
    const updateStandalone = () => setStandalone(isStandaloneRuntimeActive());
    window.addEventListener(RUNTIME_MODE_CHANGE_EVENT, updateStandalone);
    window.addEventListener("storage", updateStandalone);
    return () => {
      window.removeEventListener(RUNTIME_MODE_CHANGE_EVENT, updateStandalone);
      window.removeEventListener("storage", updateStandalone);
    };
  }, []);

  useEffect(() => {
    if (outletRef.current) {
      outletRef.current.scrollTop = 0;
      outletRef.current.scrollLeft = 0;
    }
  }, [location.pathname]);

  return (
    <div className="app-shell" data-standalone={standalone ? "true" : "false"}>
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
          <nav aria-label={t(mobileSubnav.ariaLabelKey)} className="mobile-subnav">
            {mobileSubnav.items.map((item) => (
              <NavLink className="mobile-subnav__item" end={item.end} key={item.to} to={item.to}>
                {t(item.labelKey)}
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
