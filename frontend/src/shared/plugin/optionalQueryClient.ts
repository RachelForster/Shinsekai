import * as ReactQuery from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { createContext, useContext } from "react";

const FALLBACK_QUERY_CLIENT_CONTEXT = createContext<QueryClient | undefined>(undefined);

export function hasUseQueryExport(): boolean {
  return Object.prototype.hasOwnProperty.call(ReactQuery, "useQuery");
}

export function useOptionalQueryClient(): QueryClient | undefined {
  const context = Object.prototype.hasOwnProperty.call(ReactQuery, "QueryClientContext")
    ? ReactQuery.QueryClientContext
    : FALLBACK_QUERY_CLIENT_CONTEXT;
  return useContext(context);
}
