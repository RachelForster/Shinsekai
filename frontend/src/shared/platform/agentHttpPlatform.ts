import type { AgentPlatform } from "./agentTypes";

export function createAgentHttpPlatform(request: <T>(path: string, init?: RequestInit) => Promise<T>): AgentPlatform {
  const post = <T>(path: string, body: unknown = {}) =>
    request<T>(`/api/agent${path}`, { method: "POST", body: JSON.stringify(body) });
  const id = encodeURIComponent;
  return {
    runtime: (signal) => request("/api/agent/runtime", { signal }),
    start: () => post("/runtime/start"),
    resumeQueue: () => post("/queue/resume"),
    listBackends: () => request("/api/agent/backends"),
    listSessions: (cursor, signal) =>
      request(`/api/agent/sessions?limit=1000${cursor ? `&cursor=${id(cursor)}` : ""}`, { signal }),
    createSession: () => post("/sessions"),
    closeSession: async (sessionId) => {
      await post(`/sessions/${id(sessionId)}/close`);
    },
    listTasks: (sessionId, cursor, signal) =>
      request(`/api/agent/tasks?sessionId=${id(sessionId)}&limit=1000${cursor ? `&cursor=${id(cursor)}` : ""}`, {
        signal,
      }),
    submitTask: (sessionId, input) => post(`/sessions/${id(sessionId)}/tasks`, input),
    getTask: (taskId) => request(`/api/agent/tasks/${id(taskId)}`),
    readEvents: (taskId, afterSeq, signal) =>
      request(`/api/agent/tasks/${id(taskId)}/events?afterSeq=${afterSeq}&limit=1000`, { signal }),
    cancelTask: (taskId) => post(`/tasks/${id(taskId)}/cancel`),
    respondInput: (taskId, input) => post(`/tasks/${id(taskId)}/input`, input),
    readArtifact: (artifactId, revision) => request(`/api/agent/artifacts/${id(artifactId)}?revision=${id(revision)}`),
  };
}
