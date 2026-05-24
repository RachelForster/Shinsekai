import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { queryClient } from "../../shared/async/queryClient";
import { I18nProvider } from "../../shared/i18n";
import { ToastProvider } from "../../shared/ui";
import { AppStateProvider, useAppState } from "./AppState";

function LocalizedProviders({ children }: { children: ReactNode }) {
  const { state } = useAppState();
  return (
    <I18nProvider language={state.language}>
      <ToastProvider>{children}</ToastProvider>
    </I18nProvider>
  );
}

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AppStateProvider>
        <LocalizedProviders>{children}</LocalizedProviders>
      </AppStateProvider>
    </QueryClientProvider>
  );
}
