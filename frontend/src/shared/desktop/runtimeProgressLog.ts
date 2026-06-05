import type { DesktopRuntimeProgress } from "./desktopApi";

const maxRuntimeLogLines = 240;

export function appendRuntimeProgressLog(
  current: DesktopRuntimeProgress | null,
  progress: DesktopRuntimeProgress,
): DesktopRuntimeProgress {
  if (progress.phase !== "installingDeps") {
    return progress;
  }
  const line = progress.logLine?.trimEnd();
  const previous = current?.phase === "installingDeps" ? (current.logLines ?? []) : [];
  if (!line) {
    return { ...progress, logLines: previous };
  }
  return {
    ...progress,
    logLines: [...previous, line].slice(-maxRuntimeLogLines),
  };
}
