import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { agentApi, agentQueryKey, listAgentTasks } from "../../entities/agent/repository";
import { emptyTranscript, isTerminal, mergeAgentEvents, type AgentTranscript } from "../../entities/agent/events";

export function useAgentConversation(sessionId: string, enabled: boolean) {
  const client = useQueryClient();
  const tasks = useQuery({
    queryKey: [...agentQueryKey, "tasks", sessionId],
    queryFn: ({ signal }) => listAgentTasks(sessionId, signal),
    enabled: enabled && !!sessionId,
    refetchInterval: enabled ? 1000 : false,
    retry: false,
  });
  const key = [...agentQueryKey, "transcript", sessionId];
  const version = tasks.data?.map((task) => `${task.taskId}:${task.status}`).join("|") ?? "";
  const transcript = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const previous = client.getQueryData<Record<string, AgentTranscript>>(key) ?? {};
      const pairs: Array<readonly [string, AgentTranscript]> = [];
      const history = tasks.data ?? [];
      for (let offset = 0; offset < history.length; offset += 8) {
        pairs.push(
          ...(await Promise.all(
            history.slice(offset, offset + 8).map(async (task) => {
              let value = previous[task.taskId] ?? emptyTranscript(task.taskId);
              if (value.hydrated && value.status === task.status) return [task.taskId, value] as const;
              for (let page = 0; page < 4; page += 1) {
                const cursor = value.nextSeq;
                value = mergeAgentEvents(value, await agentApi().readEvents(task.taskId, cursor, signal));
                if (value.nextSeq === cursor) {
                  value = { ...value, hydrated: isTerminal(task.status), status: task.status };
                  break;
                }
              }
              return [task.taskId, value] as const;
            }),
          )),
        );
      }
      return Object.fromEntries(pairs);
    },
    enabled: enabled && !!tasks.data?.length,
    refetchInterval: (query) =>
      enabled &&
      (tasks.data?.some((task) => !isTerminal(task.status)) ||
        Object.values(query.state.data ?? {}).some((item) => !item.hydrated))
        ? 500
        : false,
    retry: false,
  });
  useEffect(() => {
    if (enabled && version) void client.invalidateQueries({ queryKey: [...agentQueryKey, "transcript", sessionId] });
  }, [client, enabled, sessionId, version]);
  return { tasks, transcript };
}
