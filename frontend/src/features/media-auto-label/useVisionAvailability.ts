import { useQuery } from "@tanstack/react-query";

import { configQueryKey, getAppConfig } from "../../entities/config/repository";

export function useVisionAvailability() {
  const query = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey, staleTime: 30_000 });
  return Boolean(query.data?.vision_available);
}
