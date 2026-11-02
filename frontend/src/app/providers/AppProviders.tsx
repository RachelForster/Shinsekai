import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import { browseFiles } from "../../entities/files/repository";
import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import { ChatThemeProvider } from "../../features/chat-stage/theme/ChatThemeProvider";
import { queryClient } from "../../shared/async/queryClient";
import { AppStateProvider, useAppState } from "../../shared/app-state/AppState";
import { I18nProvider } from "../../shared/i18n";
import { applyThemeColor } from "../../shared/theme/appTheme";
import { FileBrowserProvider, ToastProvider } from "../../shared/ui";

function AppI18nProvider({ children }: { children: ReactNode }) {
  const { state } = useAppState();

  return <I18nProvider language={state.language}>{children}</I18nProvider>;
}

export function AppRuntimeProviders({ children }: { children: ReactNode }) {
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });

  useEffect(() => {
    applyThemeColor(configQuery.data?.system_config?.theme_color);
  }, [configQuery.data?.system_config?.theme_color]);

  return (
    <FileBrowserProvider browse={browseFiles}>
      <ToastProvider>
        <ChatThemeProvider>{children}</ChatThemeProvider>
      </ToastProvider>
    </FileBrowserProvider>
  );
}

export function AppRootProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AppStateProvider>
        <AppI18nProvider>{children}</AppI18nProvider>
      </AppStateProvider>
    </QueryClientProvider>
  );
}

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <AppRootProviders>
      <AppRuntimeProviders>{children}</AppRuntimeProviders>
    </AppRootProviders>
  );
}
