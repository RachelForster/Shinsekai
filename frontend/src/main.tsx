import React from "react";
import ReactDOM from "react-dom/client";

import { AppProviders } from "./app/providers/AppProviders";
import { AppRoutes } from "./app/routes/AppRoutes";
import { ErrorBoundary } from "./shared/ui";
import "./shared/theme/color.css";
import "./shared/theme/tokens.css";
import "./shared/theme/global.css";
import "./shared/theme/settings-base.css";
import "./app/shell/shell.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <AppProviders>
        <AppRoutes />
      </AppProviders>
    </ErrorBoundary>
  </React.StrictMode>,
);
