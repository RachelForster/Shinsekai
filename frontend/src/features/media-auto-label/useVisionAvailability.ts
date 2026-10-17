import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import { getPluginLoadStatus, pluginLoadStatusQueryKey } from "../../entities/plugin/repository";

export function useVisionAvailability() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey, staleTime: 30_000 });
  const pluginStatusQuery = useQuery({
    queryFn: getPluginLoadStatus,
    queryKey: pluginLoadStatusQueryKey,
    refetchInterval: (statusQuery) => {
      if (statusQuery.state.status === "error") {
        return false;
      }
      const status = statusQuery.state.data?.status;
      return status === "ready" || status === "error" ? false : 250;
    },
  });
  const visionAvailable = query.data?.vision_available;
  const pluginsReady = pluginStatusQuery.data?.status === "ready";

  useEffect(() => {
    if (pluginsReady && visionAvailable === false) {
      void queryClient.invalidateQueries({ exact: true, queryKey: configQueryKey });
    }
  }, [pluginsReady, queryClient, visionAvailable]);

  return Boolean(visionAvailable);
}
