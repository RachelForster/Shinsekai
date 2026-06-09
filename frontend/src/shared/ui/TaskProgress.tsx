import "./TaskProgress.css";

interface TaskProgressSnapshot {
  errorUserMessage?: string;
  fallbackAllowed?: boolean;
  logs?: readonly string[];
  message?: string;
  notice?: string;
  noticeKind?: "error" | "info" | "warning";
  phase: string;
  progress?: number | null;
  status: string;
}

interface TaskProgressProps {
  logLimit?: number;
  task: TaskProgressSnapshot | null;
}

function taskPercent(progress: number | null | undefined) {
  if (progress == null) {
    return null;
  }
  return Math.min(100, Math.max(0, Math.round(progress * 100)));
}

export function TaskProgress({ logLimit = 6, task }: TaskProgressProps) {
  if (!task) {
    return null;
  }

  const percent = taskPercent(task.progress);
  const logs = logLimit > 0 ? (task.logs ?? []).slice(-logLimit) : [];
  const notice = task.notice || (task.status === "failed" ? task.errorUserMessage : "");
  const noticeKind = task.noticeKind || (task.status === "failed" ? "error" : "info");
  const message = task.message || task.status;
  const showMessage = message !== notice;

  return (
    <div className="task-progress" role="status" aria-live="polite">
      <div className="task-progress__meta">
        <strong>{task.phase}</strong>
        <span>{percent == null ? task.status : `${percent}%`}</span>
      </div>
      {percent == null ? null : (
        <div className="task-progress__track" aria-hidden>
          <span className="task-progress__fill" style={{ width: `${percent}%` }} />
        </div>
      )}
      {showMessage ? <div className="task-progress__message">{message}</div> : null}
      {notice ? (
        <div className={`task-progress__notice task-progress__notice--${noticeKind}`}>
          {notice}
          {task.fallbackAllowed && task.status === "failed" ? " 可稍后重试。" : ""}
        </div>
      ) : null}
      {logs.length ? <pre className="task-progress__log">{logs.join("\n")}</pre> : null}
    </div>
  );
}
