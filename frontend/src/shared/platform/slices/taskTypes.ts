import type { StoryGenerationTask } from "./storyTypes";

export type TaskStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type PathPickerMode = "directory" | "file" | "path";

export interface FileBrowserEntry {
  kind: PathPickerMode;
  modifiedAt?: number;
  name: string;
  path: string;
  size?: number | null;
}

export interface FileBrowserRoot {
  label: string;
  path: string;
}

export interface FileBrowserSnapshot {
  cwd: string;
  entries: FileBrowserEntry[];
  parent?: string;
  roots: FileBrowserRoot[];
}

export interface TaskSnapshot<TResult = unknown> {
  cancelRequested?: boolean;
  completedItems?: number;
  createdAt: number;
  dependencyInstallStatus?: string;
  error?: string;
  errorCode?: string;
  errorDetail?: string;
  errorUserMessage?: string;
  fallbackAllowed?: boolean;
  httpStatus?: number;
  id: string;
  generationTask?: StoryGenerationTask;
  generationTaskId?: string;
  installSource?: string;
  installSourceLabel?: string;
  kind: string;
  logs: string[];
  message: string;
  notice?: string;
  noticeKind?: "error" | "info" | "warning";
  packageSha256?: string;
  packageSource?: string;
  packageStatus?: string;
  packageUrl?: string;
  phase: string;
  progress?: number | null;
  result?: TResult | null;
  status: TaskStatus;
  title: string;
  totalItems?: number;
  updatedAt: number;
}

export interface TaskProgressOptions<TResult = unknown> {
  onTaskUpdate?: (task: TaskSnapshot<TResult>) => void;
}

export interface LogStructuredEntry {
  [key: string]: unknown;
  event?: string;
  level?: string;
  line?: number;
  logger?: string;
  message?: string;
  plugin_id?: string;
  session_id?: string;
  task_id?: string;
  timestamp?: string;
}

export interface LogSnapshot {
  content: string;
  entries?: LogStructuredEntry[];
  modifiedAt?: number;
  name: string;
  path: string;
  size: number;
  truncated?: boolean;
}

export interface LogFileInfo {
  app?: string;
  modifiedAt?: number;
  name: string;
  path: string;
  relativePath?: string;
  size: number;
}

export interface LogFileList {
  files: LogFileInfo[];
}

export interface DiagnosticBundleResult {
  downloadUrl: string;
  path: string;
}

export interface RuntimeDependencyError {
  kind?: "missing_dependency";
  logPath?: string;
  message: string;
  moduleName: string;
  packageName: string;
}

export interface RuntimeDependencyInstallInput {
  moduleName: string;
  pythonPath?: string;
}

export interface RuntimeDependencyInstallResult {
  message: string;
  moduleName: string;
  packageName: string;
  pipCode?: number;
  pipOutput?: string;
}

export interface ImageAutoLabelFailure {
  index: number;
  message: string;
}

export interface ImageAutoLabelResult {
  annotatedCount: number;
  failedCount: number;
  failures: ImageAutoLabelFailure[];
  name: string;
  scope: "background" | "character";
  skippedCount: number;
  tags: string;
  totalCount: number;
}

export interface FilesPlatform {
  openT2iWorkflowFolder: () => Promise<{ path: string }>;
  modelUrl: (modelPath: string, path: string) => string;
  browse: (options?: { path?: string; showHidden?: boolean }) => Promise<FileBrowserSnapshot>;
  fileUrl: (path: string) => string;
  thumbnailBatch?: (
    paths: string[],
    options?: { delivery?: "data" | "url"; size?: number },
  ) => Promise<Record<string, string>>;
  thumbnailUrl: (path: string, options?: { size?: number }) => string;
  openExternal: (url: string) => Promise<void>;
}

export interface LogsPlatform {
  exportDiagnostics: () => Promise<DiagnosticBundleResult>;
  getDefault: () => Promise<LogSnapshot>;
  import: (items: File[] | string[]) => Promise<LogSnapshot>;
  list: () => Promise<LogFileList>;
}

export interface RuntimePlatform {
  installMissingDependency: (
    input: RuntimeDependencyInstallInput,
    options?: TaskProgressOptions<RuntimeDependencyInstallResult>,
  ) => Promise<RuntimeDependencyInstallResult>;
}

export interface TasksPlatform {
  get: <TResult = unknown>(id: string) => Promise<TaskSnapshot<TResult>>;
}
