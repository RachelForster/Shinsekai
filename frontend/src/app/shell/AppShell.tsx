import { useState } from "react";
import { Outlet } from "react-router-dom";

import { BottomBar } from "./BottomBar";
import { SidebarNav } from "./SidebarNav";
import { TopBar } from "./TopBar";

export function AppShell() {
  const [menuExpanded, setMenuExpanded] = useState(false);

  return (
    <div className={`app-shell${menuExpanded ? " app-shell--expanded" : ""}`}>
      <SidebarNav expanded={menuExpanded} onToggle={() => setMenuExpanded((expanded) => !expanded)} />
      <TopBar />
      <main className="content-outlet">
        <Outlet />
      </main>
      <BottomBar />
    </div>
  );
}
