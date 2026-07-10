import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type { ChatRuntimeProcessState, ChatSnapshot } from "../../shared/platform/types";
import { chatRuntimeStatusQueryKey, getChatRuntimeStatus, runtimeStatusFromSnapshot } from "./repository";
import { useChatRuntimeClosing } from "./runtimeState";

const RUNTIME_STATUS_POLL_INTERVAL_MS = 1200;

interface ChatLaunchGuard {
  refreshRuntimeStatus: () => Promise<void>;
  runtimeLaunchDisabled: boolean;
  updateRuntimeStatusFromSnapshot: (snapshot: ChatSnapshot) => Promise<ChatRuntimeProcessState>;
}

export function useChatLaunchGuard(): ChatLaunchGuard {
  const queryClient = useQueryClient();
  const localRuntimeClosing = useChatRuntimeClosing();
  const runtimeStatusQuery = useQuery({
    queryFn: getChatRuntimeStatus,
    queryKey: chatRuntimeStatusQueryKey,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return localRuntimeClosing || state === "running" || state === "closing"
        ? RUNTIME_STATUS_POLL_INTERVAL_MS
        : false;
    },
  });

  const updateRuntimeStatusFromSnapshot = useCallback(
    async (snapshot: ChatSnapshot) => {
      const runtimeStatus = runtimeStatusFromSnapshot(snapshot);
      await queryClient.cancelQueries({ exact: true, queryKey: chatRuntimeStatusQueryKey });
      queryClient.setQueryData(chatRuntimeStatusQueryKey, runtimeStatus);
      return runtimeStatus;
    },
    [queryClient],
  );

  const runtimeLaunchDisabled =
    localRuntimeClosing || runtimeStatusQuery.data?.state === "running" || runtimeStatusQuery.data?.state === "closing";

  const refreshRuntimeStatus = useCallback(async () => {
    await runtimeStatusQuery.refetch();
  }, [runtimeStatusQuery.refetch]);

  return {
    refreshRuntimeStatus,
    runtimeLaunchDisabled,
    updateRuntimeStatusFromSnapshot,
  };
}
