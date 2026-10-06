import type { AgentEventPage, AgentInputRequest, AgentTaskStatus, AgentUsage } from "../../shared/platform/agentTypes";

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
  usage: AgentUsage | null;
  hydrated: boolean;
  status?: AgentTaskStatus;
}

export function emptyTranscript(taskId: string): AgentTranscript {
  return { taskId, nextSeq: 0, messages: [], tools: [], input: null, usage: null, hydrated: false };
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
      )
        next.tools.push({ callId: call.callId, name: call.name, arguments: call.arguments });
    } else if (event.type === "tool.completed") {
      const result = object(payload.result);
      const tool = next.tools.find((item) => item.callId === result?.callId);
      if (tool && result && typeof result.ok === "boolean")
        tool.result = { ok: result.ok, data: result.data, error: object(result.error) as { message: string } | null };
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
