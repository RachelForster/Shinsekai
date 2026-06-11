import "./TaskProgress.css";

interface TaskProgressSnapshot {
  dependencyInstallStatus?: string;
  errorUserMessage?: string;
  fallbackAllowed?: boolean;
  installSource?: string;
  installSourceLabel?: string;
  logs?: readonly string[];
  message?: string;
  notice?: string;
  noticeKind?: "error" | "info" | "warning";
  packageSha256?: string;
  packageSource?: string;
  packageStatus?: string;
  packageUrl?: string;
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

const phaseLabels: Record<string, string> = {
  cancelled: "已取消",
  completed: "完成",
  crop: "裁剪",
  download: "下载包",
  extract: "解压",
  failed: "失败",
  generate: "生成",
  install: "安装",
  installingDeps: "安装依赖",
  manifest: "登记插件",
  merge: "合并文件",
  pipeline: "执行流程",
  pip: "安装依赖",
  probe: "探测",
  prompt: "生成提示词",
  queued: "排队",
  reload: "重新加载",
  "remove-background": "抠图",
  registry: "读取索引",
  run: "运行中",
  running: "运行中",
  verify: "校验",
  write: "写入配置",
};

const packageStatusLabels: Record<string, string> = {
  checking: "包体校验中",
  downloading: "包体下载中",
  existing: "已有目录",
  failed: "包体失败",
  fallback: "已切换源码",
  installed: "包体已校验",
  pending: "包体等待中",
  verified: "包体已校验",
};

const dependencyStatusLabels: Record<string, string> = {
  "not-required": "无需安装依赖",
  pending: "依赖等待中",
  pip_conflict: "依赖冲突",
  pip_exception: "pip 异常",
  pip_failed: "依赖失败",
  pip_ok: "依赖完成",
  pip_skip_no_requirements: "无 requirements",
  pip_timeout: "依赖超时",
  running: "依赖安装中",
};

const installSourceLabels: Record<string, string> = {
  github: "GitHub 源码",
  local: "本地插件",
  package: "官方包体",
  registry: "Registry",
  repository: "GitHub 源码",
  source: "源码安装",
};

function statusLabel(value: string | undefined, labels: Record<string, string>) {
  const key = (value ?? "").trim();
  return key ? (labels[key] ?? key) : "";
}

function compactSha(value: string | undefined) {
  const sha = (value ?? "").trim();
  if (!sha) {
    return "";
  }
  return sha.length > 16 ? `${sha.slice(0, 12)}...` : sha;
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
  const sourceLabel = task.installSourceLabel || statusLabel(task.installSource, installSourceLabels);
  const packageLabel = statusLabel(task.packageStatus, packageStatusLabels);
  const dependencyLabel = statusLabel(task.dependencyInstallStatus, dependencyStatusLabels);
  const packageSourceLabel = task.packageSource ? task.packageSource.toUpperCase() : "";
  const packageDetail = [packageLabel, packageSourceLabel].filter(Boolean).join(" / ");
  const packageSha = compactSha(task.packageSha256);
  const installDetails = [
    sourceLabel ? { label: "来源", value: sourceLabel } : null,
    packageDetail ? { label: "包体", value: packageDetail } : null,
    dependencyLabel ? { label: "依赖", value: dependencyLabel } : null,
    packageSha ? { label: "SHA256", value: packageSha } : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item));

  return (
    <div className="task-progress" role="status" aria-live="polite">
      <div className="task-progress__meta">
        <strong>{phaseLabels[task.phase] ?? task.phase}</strong>
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
      {installDetails.length ? (
        <dl className="task-progress__details" aria-label="安装详情">
          {installDetails.map((item) => (
            <div className="task-progress__detail" key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {logs.length ? <pre className="task-progress__log">{logs.join("\n")}</pre> : null}
    </div>
  );
}
