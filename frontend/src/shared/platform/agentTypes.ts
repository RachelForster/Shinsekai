export type AgentTaskStatus =
  | "queued"
  | "running"
  | "waiting_input"
  | "cancelling"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";
export interface AgentError {
  code: string;
  message: string;
  retryable?: boolean;
  details?: Record<string, unknown>;
}
export interface AgentSession {
  sessionId: string;
  backendId: string;
  backendVersion: string;
  profileId: string;
  modelRef: string;
  systemPolicyRef: string;
  skillRefs: string[];
  createdAt: string;
}
export interface AgentArtifact {
  artifactId: string;
  title: string;
  kind: string;
  mimeType: string;
  size: number;
  revision: string;
}
export interface AgentResult {
  summary: string;
  data?: unknown;
  artifacts: AgentArtifact[];
  effects: Array<{ callId: string; toolName: string; state: string; description: string }>;
  warnings: string[];
}
export interface AgentTask {
  taskId: string;
  sessionId: string;
  requestId: string;
  input: { text: string };
  status: AgentTaskStatus;
  createdAt: string;
  updatedAt: string;
  result: AgentResult | null;
  error: AgentError | null;
}
export interface AgentInputRequest {
  inputRequestId: string;
  kind: "question" | "confirmation";
  question: string;
  options: Array<{ value: string; label: string }>;
  expiresAt: string | null;
}
export interface AgentUsage {
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
}
export interface AgentActivity {
  activityId: string;
  kind: "runtime" | "model" | "tool";
  name: string;
  status: "running" | "succeeded" | "failed";
  target: string;
}
export interface AgentEvent {
  taskId: string;
  eventSeq: number;
  schemaVersion: number;
  timestamp: string;
  type: string;
  payload: Record<string, unknown>;
}
export interface AgentEventPage {
  taskId: string;
  events: AgentEvent[];
  nextSeq: number;
}
export interface AgentRuntimeSnapshot {
  preview?: boolean;
  status: "idle" | "preparing" | "ready" | "error" | "stopped";
  phase: string;
  progress: number;
  backendId: string;
  modelRef: string | null;
  configurationChanged: boolean;
  queuePaused: boolean;
  error: AgentError | null;
}
export interface AgentBackendDescriptor {
  backendId: string;
  version: string;
  availability: string;
  unavailableReason: string;
  capabilities: Record<string, boolean>;
}
export interface AgentPlatform {
  runtime: (signal?: AbortSignal) => Promise<AgentRuntimeSnapshot>;
  start: () => Promise<AgentRuntimeSnapshot>;
  resumeQueue: () => Promise<AgentRuntimeSnapshot>;
  listBackends: () => Promise<{ backends: AgentBackendDescriptor[] }>;
  listSessions: (
    cursor?: string,
    signal?: AbortSignal,
  ) => Promise<{ sessions: AgentSession[]; nextCursor: string | null }>;
  createSession: () => Promise<AgentSession>;
  closeSession: (sessionId: string) => Promise<void>;
  listTasks: (
    sessionId: string,
    cursor?: string,
    signal?: AbortSignal,
  ) => Promise<{ tasks: AgentTask[]; nextCursor: string | null }>;
  submitTask: (
    sessionId: string,
    input: { requestId: string; text: string },
  ) => Promise<{ taskId: string; status: AgentTaskStatus }>;
  getTask: (taskId: string) => Promise<AgentTask>;
  readEvents: (taskId: string, afterSeq: number, signal?: AbortSignal) => Promise<AgentEventPage>;
  cancelTask: (taskId: string) => Promise<{ task: AgentTask; accepted: boolean }>;
  respondInput: (taskId: string, input: { inputRequestId: string; value: unknown }) => Promise<AgentTask>;
  readArtifact: (
    artifactId: string,
    revision: string,
  ) => Promise<{ artifact: AgentArtifact; text: string | null; downloadRef: string | null }>;
}
