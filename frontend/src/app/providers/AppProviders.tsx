import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import { browseFiles } from "../../entities/files/repository";
import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import { queryClient } from "../../shared/async/queryClient";
import { AppStateProvider, useAppState } from "../../shared/app-state/AppState";
import { I18nProvider } from "../../shared/i18n";
import { applyThemeColor } from "../../shared/theme/appTheme";
import { FileBrowserProvider, ToastProvider } from "../../shared/ui";

function LocalizedProviders({ children }: { children: ReactNode }) {
  const { state } = useAppState();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });

  useEffect(() => {
    applyThemeColor(configQuery.data?.system_config.theme_color);
  }, [configQuery.data?.system_config.theme_color]);

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
