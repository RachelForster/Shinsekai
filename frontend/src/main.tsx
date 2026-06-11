import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";

import { AppRootProviders, AppRuntimeProviders } from "./app/providers/AppProviders";
import { AppRoutes } from "./app/routes/AppRoutes";
import { DesktopChrome } from "./shared/desktop/DesktopChrome";
import {
  desktopRestartErrorMessage,
  isDesktopBridgeConnectionError,
  isDesktopRestarting,
  writeDesktopRestartDebugLog,
} from "./shared/desktop/desktopApi";
import { ErrorBoundary } from "./shared/ui";
import "./shared/theme/color.css";
import "./shared/theme/typography.css";
import "./shared/theme/tokens.css";
import "./shared/theme/global.css";
import "./shared/theme/settings-base.css";
import "./app/shell/shell.css";
import "./shared/desktop/DesktopChrome.css";

function logGlobalBridgeError(source: string, error: unknown) {
  if (!isDesktopBridgeConnectionError(error)) {
    return;
  }
  void writeDesktopRestartDebugLog(`${source} bridge error: ${desktopRestartErrorMessage(error)}`);
}

function bridgeFetchDiagnosticUrl(input: RequestInfo | URL) {
  if (typeof input === "string") {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

function bridgeFetchDiagnosticMethod(input: RequestInfo | URL, init?: RequestInit) {
  if (init?.method) {
    return init.method.toUpperCase();
  }
  if (input instanceof Request) {
    return input.method.toUpperCase();
  }
  return "GET";
}

function isBridgeDiagnosticUrl(url: string) {
  return /^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?\//i.test(url);
}

function sanitizeBridgeDiagnosticUrl(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return url;
  }
}

function compactStack(stack: string | undefined) {
  return (stack ?? "")
    .split("\n")
    .slice(1, 8)
    .map((line) => line.trim())
    .join(" | ");
}

function installBridgeFetchDiagnostics() {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = bridgeFetchDiagnosticUrl(input);
    if (!isBridgeDiagnosticUrl(url)) {
      return nativeFetch(input, init);
    }
    const method = bridgeFetchDiagnosticMethod(input, init);
    const stack = compactStack(new Error().stack);
    try {
      return await nativeFetch(input, init);
    } catch (error) {
      void writeDesktopRestartDebugLog(
        `window.fetch bridge failure method=${method} url=${sanitizeBridgeDiagnosticUrl(
          url,
        )} restarting=${isDesktopRestarting()} error=${desktopRestartErrorMessage(error)} stack=${stack}`,
      );
      throw error;
    }
  };
}

installBridgeFetchDiagnostics();

window.addEventListener("error", (event) => {
  logGlobalBridgeError("window.error", event.error ?? event.message);
});

window.addEventListener("unhandledrejection", (event) => {
  logGlobalBridgeError("window.unhandledrejection", event.reason);
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <AppRootProviders>
        <HashRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
          <DesktopChrome>
            <AppRuntimeProviders>
              <AppRoutes />
            </AppRuntimeProviders>
          </DesktopChrome>
        </HashRouter>
      </AppRootProviders>
    </ErrorBoundary>
  </React.StrictMode>,
);
