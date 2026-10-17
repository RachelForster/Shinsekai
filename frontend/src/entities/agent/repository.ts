import { getPlatform } from "../../shared/platform/platform";
import type { AgentSession, AgentTask } from "../../shared/platform/agentTypes";

export const agentQueryKey = ["agent"] as const;
export const agentApi = () => getPlatform().agent;

export async function listAgentSessions(signal?: AbortSignal): Promise<AgentSession[]> {
  const sessions: AgentSession[] = [];
  let cursor: string | undefined;
  do {
    const page = await agentApi().listSessions(cursor, signal);
    sessions.push(...page.sessions);
    cursor = page.nextCursor ?? undefined;
  } while (cursor);
  return sessions;
}

export async function listAgentTasks(sessionId: string, signal?: AbortSignal): Promise<AgentTask[]> {
  const tasks: AgentTask[] = [];
  let cursor: string | undefined;
  do {
    const page = await agentApi().listTasks(sessionId, cursor, signal);
    tasks.push(...page.tasks);
    cursor = page.nextCursor ?? undefined;
  } while (cursor);
  return tasks;
}
