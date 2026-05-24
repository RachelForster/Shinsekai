import React from "react";
import ReactDOM from "react-dom/client";

import { AppProviders } from "./app/providers/AppProviders";
import { AppRoutes } from "./app/routes/AppRoutes";
import "./shared/theme/tokens.css";
import "./shared/theme/global.css";
import "./shared/ui/ui.css";
import "./app/shell/shell.css";
import "./features/chat-stage/chat-stage.css";
import "./features/settings-pages.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AppProviders>
      <AppRoutes />
    </AppProviders>
  </React.StrictMode>,
);
