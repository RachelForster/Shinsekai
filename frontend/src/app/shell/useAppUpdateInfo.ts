import { useQuery } from "@tanstack/react-query";

import { getAppUpdateInfo } from "../../entities/plugin/repository";

export const appUpdateInfoQueryKey = ["plugins", "app-update", "info"] as const;

export function useAppUpdateInfo() {
  return useQuery({
    queryFn: getAppUpdateInfo,
    queryKey: appUpdateInfoQueryKey,
    refetchOnWindowFocus: false,
    staleTime: 300_000,
  });
}
