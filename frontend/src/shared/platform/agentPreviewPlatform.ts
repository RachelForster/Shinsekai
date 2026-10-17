import { PlatformRequestError } from "./errors";
import type { AgentEvent, AgentPlatform, AgentSession, AgentTask, AgentTaskStatus } from "./agentTypes";

export function createAgentPreviewPlatform(): AgentPlatform {
  const sessions: AgentSession[] = [];
  const tasks: AgentTask[] = [];
  const events = new Map<string, AgentEvent[]>();
  const closed = new Set<string>();
  const terminal = (status: AgentTaskStatus) => ["succeeded", "failed", "cancelled", "interrupted"].includes(status);
  const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
  const snapshot = () => ({
    status: "ready" as const,
    phase: "ready",
    progress: 1,
    backendId: "preview",
    modelRef: "preview-model",
    configurationChanged: false,
    queuePaused: false,
    error: null,
    preview: true,
  });
  const getTask = (taskId: string) => {
    const task = tasks.find((item) => item.taskId === taskId);
    if (!task) throw new PlatformRequestError("Task not found", 400, "INVALID_REQUEST");
    return task;
  };
  const append = (task: AgentTask, type: string, payload: Record<string, unknown>) => {
    const history = events.get(task.taskId)!;
    history.push({
      taskId: task.taskId,
      eventSeq: history.length + 1,
      schemaVersion: 1,
      timestamp: new Date().toISOString(),
      type,
      payload,
    });
  };
  return {
    runtime: async () => snapshot(),
    start: async () => snapshot(),
    resumeQueue: async () => snapshot(),
    listBackends: async () => ({
      backends: [
        {
          backendId: "preview",
          version: "1",
          availability: "ready",
          unavailableReason: "",
          capabilities: { streamingText: true },
        },
      ],
    }),
    listSessions: async () => ({
      sessions: clone(sessions.filter((item) => !closed.has(item.sessionId))),
      nextCursor: null,
    }),
    createSession: async () => {
      const session: AgentSession = {
        sessionId: `as_${crypto.randomUUID()}`,
        backendId: "preview",
        backendVersion: "1",
        profileId: "basic",
        modelRef: "preview-model",
        systemPolicyRef: "agent:default",
        skillRefs: [],
        createdAt: new Date().toISOString(),
      };
      sessions.push(session);
      return clone(session);
    },
    closeSession: async (sessionId) => {
      if (tasks.some((item) => item.sessionId === sessionId && !terminal(item.status)))
        throw new PlatformRequestError("Session is busy", 409, "SESSION_BUSY");
      closed.add(sessionId);
    },
    listTasks: async (sessionId) => ({
      tasks: clone(tasks.filter((item) => item.sessionId === sessionId)),
      nextCursor: null,
    }),
    submitTask: async (sessionId, input) => {
      const previous = tasks.find((item) => item.requestId === input.requestId);
      if (previous) {
        if (previous.sessionId !== sessionId || previous.input.text !== input.text)
          throw new PlatformRequestError("Request ID conflict", 409, "IDEMPOTENCY_CONFLICT");
        return { taskId: previous.taskId, status: previous.status };
      }
      if (closed.has(sessionId) || !sessions.some((item) => item.sessionId === sessionId))
        throw new PlatformRequestError("Session not found", 400, "INVALID_REQUEST");
      const task: AgentTask = {
        taskId: `at_${crypto.randomUUID()}`,
        sessionId,
        requestId: input.requestId,
        input: { text: input.text },
        status: "running",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        error: null,
        result: null,
      };
      tasks.push(task);
      events.set(task.taskId, []);
      append(task, "task.status", { status: "running" });
      append(task, "activity.updated", {
        activityId: "preview-reply",
        kind: "model",
        name: "thinking",
        status: "running",
        target: "",
      });
      const text =
        "这是助手聊天的浏览器预览。连接新世界应用后，可以使用已配置的模型与助手对话。\n\nThis is a browser preview. Connect to the Shinsekai app to chat with your configured model.";
      setTimeout(() => {
        if (!terminal(task.status)) {
          append(task, "activity.updated", {
            activityId: "preview-reply",
            kind: "model",
            name: "responding",
            status: "running",
            target: "",
          });
          append(task, "message.delta", { messageId: "reply", delta: text.slice(0, 30) });
        }
      }, 150);
      setTimeout(() => {
        if (terminal(task.status)) return;
        append(task, "message.completed", { messageId: "reply", text });
        append(task, "activity.updated", {
          activityId: "preview-reply",
          kind: "model",
          name: "responding",
          status: "succeeded",
          target: "",
        });
        task.status = "succeeded";
        task.updatedAt = new Date().toISOString();
        task.result = { summary: text, artifacts: [], effects: [], warnings: [] };
        append(task, "task.completed", { status: "succeeded", result: task.result });
      }, 650);
      return { taskId: task.taskId, status: task.status };
    },
    getTask: async (taskId) => clone(getTask(taskId)),
    readEvents: async (taskId, afterSeq) => {
      getTask(taskId);
      const history = events.get(taskId)!;
      return { taskId, events: clone(history.filter((item) => item.eventSeq > afterSeq)), nextSeq: history.length };
    },
    cancelTask: async (taskId) => {
      const task = getTask(taskId);
      const accepted = !terminal(task.status);
      if (accepted) {
        task.status = "cancelled";
        append(task, "task.completed", { status: "cancelled" });
      }
      return { task: clone(task), accepted };
    },
    respondInput: async () => {
      throw new PlatformRequestError("No pending input", 400, "INPUT_EXPIRED");
    },
    readArtifact: async () => {
      throw new PlatformRequestError("Artifact not found", 400, "INVALID_REQUEST");
    },
  };
}
