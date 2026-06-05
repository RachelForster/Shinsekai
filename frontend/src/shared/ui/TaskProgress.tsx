import "./TaskProgress.css";

interface TaskProgressSnapshot {
  logs?: readonly string[];
  message?: string;
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
      <div className="task-progress__message">{task.message || task.status}</div>
      {logs.length ? <pre className="task-progress__log">{logs.join("\n")}</pre> : null}
    </div>
  );
}
