import { useLocation } from "react-router-dom";

import { ReminderPanel } from "../../features/reminders/ReminderPanel";
import { DesktopChrome } from "../../shared/desktop/DesktopChrome";
import { AppRuntimeProviders } from "../providers/AppProviders";
import { AppRoutes } from "./AppRoutes";

/** Select each desktop window's layout without gating reminders on chat startup. */
export function AppWindowRoutes() {
  const { pathname } = useLocation();
  if (pathname === "/reminders") return <ReminderPanel />;
  return (
    <DesktopChrome>
      <AppRuntimeProviders>
        <AppRoutes />
      </AppRuntimeProviders>
    </DesktopChrome>
  );
}
