import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      gcTime: 30 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60_000,
    },
    mutations: {
      retry: 0,
    },
  },
});
