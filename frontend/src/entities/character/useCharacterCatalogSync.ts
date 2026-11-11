import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { charactersQueryKey, getCharactersRevision } from "./repository";

// Agent writes happen in the host, independently of the drawer or selected session.
// Poll only the small version token and reload the catalog when it changes.
export function useCharacterCatalogSync() {
  const client = useQueryClient();
  const { data: revision } = useQuery({
    queryKey: ["character-catalog-revision"],
    queryFn: getCharactersRevision,
    staleTime: 0,
    refetchInterval: 1000,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    if (revision !== undefined) void client.invalidateQueries({ queryKey: charactersQueryKey });
  }, [client, revision]);
}
