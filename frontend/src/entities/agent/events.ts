import type {
  AgentActivity,
  AgentEventPage,
  AgentInputRequest,
  AgentTaskStatus,
  AgentUsage,
} from "../../shared/platform/agentTypes";

export interface AgentActivityEntry extends AgentActivity {
  startedAt: string;
  updatedAt: string;
  eventSeq: number;
  hostCallId?: string;
}

export interface AgentTranscript {
  taskId: string;
  nextSeq: number;
  messages: Array<{ id: string; text: string; complete: boolean }>;
  tools: Array<{
    callId: string;
    name: string;
    arguments: unknown;
    result?: { ok: boolean; data?: unknown; error?: { message: string } | null };
  }>;
  input: AgentInputRequest | null;
  activities: AgentActivityEntry[];
  usage: AgentUsage | null;
  hydrated: boolean;
  status?: AgentTaskStatus;
}

export function emptyTranscript(taskId: string): AgentTranscript {
  return { taskId, nextSeq: 0, messages: [], tools: [], activities: [], input: null, usage: null, hydrated: false };
}

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function mergeAgentEvents(previous: AgentTranscript, page: AgentEventPage): AgentTranscript {
  if (page.taskId !== previous.taskId) return previous;
  const next: AgentTranscript = {
    ...previous,
    messages: previous.messages.map((item) => ({ ...item })),
    tools: previous.tools.map((item) => ({ ...item })),
    activities: (previous.activities ?? []).map((item) => ({ ...item })),
  };
  for (const event of page.events) {
    if (event.taskId !== next.taskId || event.eventSeq <= next.nextSeq) continue;
    next.nextSeq = event.eventSeq;
    const payload = event.payload;
    if (event.type === "message.delta" || event.type === "message.completed") {
      if (typeof payload.messageId !== "string") continue;
      let message = next.messages.find((item) => item.id === payload.messageId);
      if (!message) {
        message = { id: payload.messageId, text: "", complete: false };
        next.messages.push(message);
      }
      if (event.type === "message.completed" && typeof payload.text === "string") {
        message.text = payload.text;
        message.complete = true;
      } else if (!message.complete && typeof payload.delta === "string") message.text += payload.delta;
    } else if (event.type === "tool.started") {
      const call = object(payload.call);
      if (
        call &&
        typeof call.callId === "string" &&
        typeof call.name === "string" &&
        !next.tools.some((item) => item.callId === call.callId)
      ) {
        next.tools.push({ callId: call.callId, name: call.name, arguments: call.arguments });
        const args = object(call.arguments);
        const params = object(args?.params);
        const body = object(args?.body);
        const pluginCall = args?.operation === "plugins.tools.invoke";
        const pluginArguments = pluginCall ? object(body?.arguments) : null;
        const target = pluginCall
          ? (pluginArguments?.query ?? pluginArguments?.url ?? pluginArguments?.selector ?? params?.plugin_id)
          : (params?.name ?? params?.plugin_id ?? body?.name ?? body?.source ?? body?.path);
        next.activities.push({
          activityId: `host:${call.callId}`,
          kind: "tool",
          name:
            pluginCall && typeof params?.tool_name === "string"
              ? params.tool_name
              : typeof args?.operation === "string"
                ? args.operation
                : call.name,
          target: typeof target === "string" ? target.slice(0, 512) : "",
          status: "running",
          startedAt: event.timestamp,
          updatedAt: event.timestamp,
          eventSeq: event.eventSeq,
          hostCallId: call.callId,
        });
      }
    } else if (event.type === "tool.completed") {
      const result = object(payload.result);
      const tool = next.tools.find((item) => item.callId === result?.callId);
      if (tool && result && typeof result.ok === "boolean") {
        tool.result = { ok: result.ok, data: result.data, error: object(result.error) as { message: string } | null };
        const activity = next.activities.find((item) => item.hostCallId === result.callId);
        if (activity) {
          activity.status = result.ok ? "succeeded" : "failed";
          activity.updatedAt = event.timestamp;
          activity.eventSeq = event.eventSeq;
        }
      }
    } else if (event.type === "activity.updated") {
      if (
        typeof payload.activityId !== "string" ||
        typeof payload.name !== "string" ||
        !["runtime", "model", "tool"].includes(String(payload.kind)) ||
        !["running", "succeeded", "failed"].includes(String(payload.status)) ||
        typeof payload.target !== "string"
      )
        continue;
      const value = payload as unknown as AgentActivity;
      const activity = next.activities.find((item) => item.activityId === value.activityId);
      if (activity) {
        Object.assign(activity, value, { updatedAt: event.timestamp, eventSeq: event.eventSeq });
      } else {
        next.activities.push({
          ...value,
          startedAt: event.timestamp,
          updatedAt: event.timestamp,
          eventSeq: event.eventSeq,
        });
      }
    } else if (event.type === "input.requested") {
      if (typeof payload.inputRequestId === "string" && typeof payload.question === "string")
        next.input = payload as unknown as AgentInputRequest;
    } else if (event.type === "input.resolved") {
      if (object(payload.answer)?.inputRequestId === next.input?.inputRequestId) next.input = null;
    } else if (event.type === "usage.updated") next.usage = payload as unknown as AgentUsage;
    else if (event.type === "task.completed") next.input = null;
  }
  next.nextSeq = Math.max(next.nextSeq, page.nextSeq);
  return next;
}

export function isTerminal(status: AgentTaskStatus) {
  return ["succeeded", "failed", "cancelled", "interrupted"].includes(status);
}
