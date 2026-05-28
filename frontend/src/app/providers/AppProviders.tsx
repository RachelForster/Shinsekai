import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { browseFiles } from "../../entities/files/repository";
import { queryClient } from "../../shared/async/queryClient";
import { AppStateProvider, useAppState } from "../../shared/app-state/AppState";
import { I18nProvider } from "../../shared/i18n";
import { FileBrowserProvider, ToastProvider } from "../../shared/ui";

function LocalizedProviders({ children }: { children: ReactNode }) {
  const { state } = useAppState();
  return (
    <I18nProvider language={state.language}>
      <FileBrowserProvider browse={browseFiles}>
        <ToastProvider>{children}</ToastProvider>
      </FileBrowserProvider>
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
